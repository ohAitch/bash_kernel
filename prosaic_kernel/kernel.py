"""A ML kernel for Jupyter"""
import html
from metakernel import MetaKernel, ExceptionWrapper, Magic
import anthropic

import os, sys
from pathlib import Path
from typing import Optional
import traceback

__version__ = '0.0.2'

#STUB
async def make_tool_interface(_connection):
    connection = _connection
    async def tool(code):
        return f"{connection} ran: {code}"
    return tool

VALIDATION_PROMPT = "\n\n" + (Path(__file__).parent / "validation_prompt.md").read_text().strip()

class EnvClient(anthropic.Client):
    def __init__(self) -> None:
        super().__init__(os.environ["ANTHROPIC_API_KEY"])

class AnthropicQuery:
    def __init__(self, query: str, prefix="", raw=False, client: Optional[anthropic.Client] = None) -> None:
        self.client = client or EnvClient()
        if raw:
            self.query_prompt = query
        else:
            self.query_prompt = f"{anthropic.HUMAN_PROMPT} {query}{anthropic.AI_PROMPT}"
        self.answer = None
        self.api_args = dict(
            prompt = prefix + self.query_prompt,
            stop_sequences=[anthropic.HUMAN_PROMPT],
            max_tokens_to_sample=500,  #TODO configure max_tokens model etc
            model="claude-instant-v1",
        )
    
    def sync(self, **kwargs):
        self.answer = self.client.completion(**{**self.api_args, **kwargs})['completion']
        return self.answer

    def stream(self, **kwargs):
        for message in self.client.completion_stream(**{**self.api_args, **kwargs}):
            self.answer = message['completion']
            yield self.answer
    
    def prompt_and_answer(self):
        if self.answer is not None: return self.query_prompt + self.answer

from metakernel import Magic

class ValidationAllowMagic(Magic):
    def line_prosaic_validation_allow(self):
        """
        %prosaic_validation_allow - enable code execution tool

        This line magic is used to enable executing model code.

        Examples:
            %prosaic_validation_allow
        """

        self.retval = self.kernel.prosaic_validation_allow()

    def post_process(self, retval):
        return self.retval

#TODO multiple code blocks, be less brittle
def code_block(response):
    in_code = False
    for line in response.splitlines():
        if   line == "```python":  in_code = True
        elif line == "```":        return
        elif in_code:              yield line

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

    def prosaic_validation_allow(self):
        r = "Enabled!" + " (Was already enabled.)" * self._validation_enabled
        self._validation_enabled = True
        return r
    
    def __init__(self, *args, prosaic_container="STUB", **kwargs):
        super().__init__(*args, **kwargs)
        self._known_display_ids = set()
        self.chat_log = [""]
        self.prosaic_container = prosaic_container
        self._exec_tool = None
        self._validation_enabled = False
        self.register_magics(ValidationAllowMagic)

    async def exec_tool(self, code):
        if not self._exec_tool:
            self._exec_tool = await make_tool_interface(self.prosaic_container)
        return await self._exec_tool(code)

    async def try_exec_code_blocks(self, response):
        code = "\n".join(code_block(response))
        if not code.strip():
            return None
        self.Print("\n---\n" )
        query = AnthropicQuery(VALIDATION_PROMPT.format(CODE=code), raw=True)
        if " Yes" == query.sync(model="claude-v1", max_tokens_to_sample=1):
            self.Print(await self.exec_tool(code))
        elif self.approve_interactively(code):
            self.Print("Approved!")
            #REVIEW log code contents maybe
            self.Print(await self.exec_tool(code))
        else:
            self.Print("Rejected.")

    def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False):
        self.silent = silent
        self._store_history = store_history
        return super().do_execute(code, silent, store_history, user_expressions, allow_stdin)

    async def do_execute_direct(self, code):
        if not code.strip():
            return None
        try:
            if code[0] == '!' or code[0] == '<':
                return self._do_command(code)
            query = AnthropicQuery(code.strip(), prefix="".join(self.chat_log))
            for message in query.stream():
                self.clear_output(wait=True)
                self.Print(message)
                #TODO format model response as markdown
            
            if query.prompt_and_answer():
                self.chat_log.append(query.prompt_and_answer())
            
            if self._validation_enabled and query.answer:
                return await self.try_exec_code_blocks(query.answer)

        except KeyboardInterrupt:
            self.kernel_resp =  {'status': 'abort', 'execution_count': self.execution_count}
        except Exception as error:
            return self.wrap_exception(error,*sys.exc_info())
        return None

    def wrap_exception(self, error, ex_type, ex, tb):
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
                self.chat_log = [""]
                if len(code.splitlines()[1:]):
                    #TODO split on anthropic.HUMAN_PROMPT
                    prompt = "\n\n" + "\n".join(code.splitlines()[1:]).strip()
                    self.chat_log[0]=prompt
                lines = self.chat_log[0].count('\n')
                self.process_output(f"Reset! Prompt is {lines} lines.")
                return None
            case "!nb" | "<!--":
                self.Print("[Ignoring...]")
                return None
            case _:
                raise Exception(f"Unknown command {code.splitlines()[0]}")

    #TODO gracefully handle KeyboardInterrupt
    kernel_javascript = '''
        const CodeCell = window.IPython.CodeCell;

        CodeCell.prototype._handle_input_request = function(msg) {
            this.output_area.append_raw_input(msg); // original code

            if (/^\s*<form data-prosaic-override>/.test(msg.content.prompt)){
                let container = this.output_area.element.find('.raw_input_container')
                container.html(container.text())
                container.find('form').submit(() => {
                    IPython.notebook.kernel.send_input_reply(document.activeElement.name);
                    container.remove()
                    return false
                })
            }
        }
    '''
    #REVIEW style me?
    def approve_interactively(self, code):
        return "approved" == self.raw_input(f'''
            <form data-prosaic-override>
                <h4>Would you like to run this code?</h4>
                <pre>{html.escape(code)}</pre>
                <input type="submit" name="approved" value="Approve">
                <input type="submit" name="rejected" value="Reject">
            </form>
        ''')