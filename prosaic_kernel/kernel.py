"""A ML kernel for Jupyter"""
import logging
from metakernel import MetaKernel, ExceptionWrapper
import anthropic

import os, re, sys
from typing import Optional
import traceback

__version__ = '0.0.2'

version_pat = re.compile(r'version (\d+(\.\d+)+)')

from .display import extract_contents

class EnvClient(anthropic.Client):
    def __init__(self) -> None:
        super().__init__(os.environ["ANTHROPIC_API_KEY"])

class AnthropicQuery:
    def __init__(self, query: str, prefix="", client: Optional[anthropic.Client] = None) -> None:
        self.client = client or EnvClient()
        self.query_prompt = f"{anthropic.HUMAN_PROMPT} {query}{anthropic.AI_PROMPT}"
        self.answer = None
        self.api_args = dict(
            prompt = prefix + self.query_prompt,
            stop_sequences=[anthropic.HUMAN_PROMPT],
            max_tokens_to_sample=500,  #TODO configure max_tokens model etc
            model="claude-instant-v1",
        )
    
    def sync(self, **kwargs):
        self.answer = self.client.completion(**self.api_args, **kwargs)['completion']
        return self.answer

    def stream(self, **kwargs):
        for message in self.client.completion_stream(**self.api_args, **kwargs):
            self.answer = message['completion']
            yield self.answer
    
    def prompt_and_answer(self):
        if self.answer is not None: return self.query_prompt + self.answer


class MetaKernelProsaic(MetaKernel):
    implementation = 'Prosaic Kernel'
    implementation_version = __version__
    
    language = 'markdown'
    language_version = anthropic.ANTHROPIC_CLIENT_VERSION

    banner = "Prosaic kernel - ask and we shall answer" #REVIEW
    language_info = {'name': 'prosaic',
                     'codemirror_mode': 'markdown',
                     'mimetype': 'text/x-markdown-prompt',
                     'file_extension': '.md',
                     'help_links': MetaKernel.help_links,}

    @property
    def kernel_json(self):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            #REVIEW with %env magics, this could also be loaded at runtime?
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


    def process_output(self, output):
        if not self.silent:
            if isinstance(output, Exception):
                message = {'name': 'stderr', 'text': str(output)}
                self.send_response(self.iopub_socket, 'stream', message)
                return
                
            plain_output, rich_contents = extract_contents(output)

            # Send standard output
            if plain_output:
                stream_content = {'name': 'stdout', 'text': plain_output}
                self.send_response(self.iopub_socket, 'stream', stream_content)

            # Send rich contents, if any:
            for content in rich_contents:
                if isinstance(content, Exception):
                    message = {'name': 'stderr', 'text': str(e)}
                    self.send_response(self.iopub_socket, 'stream', message)
                else:
                    if 'transient' in content and 'display_id' in content['transient']:
                        self._send_content_to_display_id(content)
                    else:
                        self.send_response(self.iopub_socket, 'display_data', content)

    def _send_content_to_display_id(self, content):
        """If display_id is not known, use "display_data", otherwise "update_display_data"."""
        # Notice this is imperfect, because when re-running the same cell, the output cell
        # is destroyed and the div element (the html tag) with the display_id no longer exists. But the
        # `update_display_data` function has no way of knowing this, and thinks that the
        # display_id still exists and will try, and fail to update it (as opposed to re-create
        # the div with the display_id).
        #
        # The solution is to have the user always to generate a new display_id for a cell: this
        # way `update_display_data` will not have seen the display_id when the cell is re-run and
        # correctly creates the new div element.
        display_id = content['transient']['display_id']
        if display_id in self._known_display_ids:
            msg_type = 'update_display_data'
        else:
            msg_type = 'display_data'
            self._known_display_ids.add(display_id)
        self.send_response(self.iopub_socket, msg_type, content)

    def update_output(self, text):
        stdout_text = {'name': 'stdout', 'text': text}
        self.send_response(self.iopub_socket, 'clear_output', {'wait': True})
        self.send_response(self.iopub_socket, 'stream', stdout_text)
        #MAYFIX handle images html etc
        #self.process_output(completion)

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
                self.update_output(message)
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
                self.process_output("".join(self.chat_log))
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
                self.process_output(f"Reset! Prompt is {lines} lines.")
                return None
            case "!nb" | "<!--":
                self.process_output("[Ignoring...]")
                return None
            case _:
                raise Exception(f"Unknown command {code.splitlines()[0]}")