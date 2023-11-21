"""A ML kernel for Jupyter"""
from metakernel import MetaKernel, ExceptionWrapper
import anthropic

import os, sys
from typing import Optional
import traceback

__version__ = '0.0.2'

class EnvClient(anthropic.Anthropic):
    def __init__(self) -> None:
        super().__init__()

class AnthropicQuery:
    def __init__(self, query: str, prefix="", client: Optional[anthropic.Anthropic] = None) -> None:
        self.client = client or EnvClient()
        self.query_prompt = f"{anthropic.HUMAN_PROMPT} {query}{anthropic.AI_PROMPT}"
        self.answer = None
        self.api_args = dict(
            prompt = prefix + self.query_prompt,
            stop_sequences=[anthropic.HUMAN_PROMPT],
            max_tokens_to_sample=800,  #TODO configure max_tokens model etc
            model="	claude-instant-1",
        )
    
    def sync(self, **kwargs):
        self.answer = self.client.completions.create(**self.api_args, **kwargs).completion
        return self.answer

    def stream(self, **kwargs):
        for message in self.client.completions.create(**self.api_args, **kwargs, stream=True):
            self.answer += message.completion
            yield message.completion
    
    def prompt_and_answer(self):
        if self.answer is not None: return self.query_prompt + self.answer

class MetaKernelProsaic(MetaKernel):
    implementation = 'Prosaic Kernel'
    implementation_version = __version__
    
    language = 'markdown'
    language_version = anthropic.__version__

    banner = "Prosaic kernel - ask and we shall answer" #REVIEW
    language_info = {'name': 'prosaic',
                     'codemirror_mode': 'markdown',
                     'mimetype': 'text/x-markdown-prompt',
                     'file_extension': '.md',
                     'help_links': MetaKernel.help_links,}

    @property
    def kernel_json(self):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            #REVIEW with %set magic, this could also be loaded at runtime?
            print("ANTHROPIC_API_KEY unset or blank. Please set it to your API key.")
            sys.exit(1)
        return {
            "argv":[sys.executable,"-m","prosaic_kernel", "-f", "{connection_file}"],
            "display_name":"Prosaic",
            "language":"markdown",
            "codemirror_mode":"markdown",
            'name': 'prosaic',
            'env': {
                "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
            },
         }

    def get_usage(self):
        return "Ask a question!"

    #TODO replace _do_command w/ magics
    magic_prefixes = dict(magic='%', shell='DISABLED!', help='?')
    #TODO really this is a tweak to self.parser - kind of a lot of legitimate one-line queries end with '?'
    help_suffix = "DISABLED?DISABLED"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._known_display_ids = set()
        self.chat_log = []

    def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False):
        self.silent = silent
        return super().do_execute(code, silent, store_history, user_expressions, allow_stdin)

    #TODO async!
    def do_execute_direct(self, code):
        if not code.strip():
            return None
        try:
            if code[0] == '!' or code[0] == '<':
                return self._do_command(code)

            query = AnthropicQuery(code.strip(), prefix="".join(self.chat_log))
            for message in query.stream():
                self.Print(message, end="")
            if query.prompt_and_answer():
                self.chat_log.append(query.prompt_and_answer())
        except KeyboardInterrupt:
            self.kernel_resp =  {'status': 'abort', 'execution_count': self.execution_count}
        except Exception as error:
            return self.wrap_exception(error,*sys.exc_info())
        return None

    def wrap_exception(error, ex_type, ex, tb):
        # see metakernel.magics.python_magic.exec_then_eval
        line1 = ["Traceback (most recent call last):"]
        line2 = ["%s: %s" % (ex.__class__.__name__, str(ex))]
        tb_format = line1 + [line.rstrip() for line in traceback.format_tb(tb)[1:]] + line2
        return ExceptionWrapper(ex_type.__name__, repr(error.args), tb_format)

    def _do_command(self,code):
        match code.splitlines()[0]:
            case "!log":
                self.Print("".join(self.chat_log))
                if len(code.splitlines()[1:]):
                    raise Exception("!log takes no input")
                return None
            case "!reset":
                self.chat_log = []
                if len(code.splitlines()[1:]):
                    #TODO split on anthropic.HUMAN_PROMPT
                    prompt = "\n\n" + "\n".join(code.splitlines()[1:]).strip()
                    self.chat_log.append(prompt)
                lines = (self.chat_log or [""])[0].count('\n')
                self.Print(f"Reset! Prompt is {lines} lines.")
                return None
            case "!nb" | "<!--":
                self.Print("[Ignoring...]")
                return None
            case _:
                raise Exception(f"Unknown command {code.splitlines()[0]}")