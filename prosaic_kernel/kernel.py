from ipykernel.kernelbase import Kernel

import anthropic

import os
import re

from pathlib import Path
__version__ = '0.0.1'

version_pat = re.compile(r'version (\d+(\.\d+)+)')

from .display import content_for_js, extract_contents

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
    def __init__(self, client: anthropic.Client, query: str, prefix="", raw=False) -> None:
        self.client = client
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

class ProsaicKernel(Kernel):
    implementation = 'prosaic_kernel'
    implementation_version = __version__

    @property
    def language_version(self):
        m = version_pat.search(self.banner)
        return m.group(1)

    _banner = None

    @property
    def banner(self):
        if self._banner is None:
            self._banner = "v0" # check_output(['bash', '--version']).decode('utf-8')
        return self._banner

    language_info = {'name': 'prosaic',
                     'codemirror_mode': 'markdown',
                     'mimetype': 'text/x-markdown-prompt',
                     'file_extension': '.md'}

    def __init__(self, prosaic_container="STUB", **kwargs):
        Kernel.__init__(self, **kwargs)
        self._known_display_ids = set()
        self.chat_log = [""]
        self.prosaic_container = prosaic_container
        self._exec_tool = None

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

    async def exec_tool(self, code):
        if not self._exec_tool:
            self._exec_tool = await make_tool_interface(self.prosaic_container)
        return await self._exec_tool(code)

    async def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False):
        self.silent = silent
        self._allow_stdin = allow_stdin
        if not code.strip():
            return {'status': 'ok', 'execution_count': self.execution_count,
                    'payload': [], 'user_expressions': {}}

        try:
            if os.environ.get("PROSAIC_VALIDATION_MODE"):
                if store_history:
                     #TODO the mapping to self.execution_count could be less fragile
                    self.chat_log.append(code.strip())
                
                query = AnthropicQuery(EnvClient(), VALIDATION_PROMPT.format(CODE=code), raw=True)
                if " Yes" == query.sync(model="claude-v1", max_tokens_to_sample=1):
                    self.update_output(await self.exec_tool(code))
                else:
                    #TODO really this should go in kernel.js
                    self.send_response(self.iopub_socket, 'display_data', content_for_js('''
                        console.warn("TODO inject fancy approve/reject <form>")
                    '''))
                    #TODO display the code in question in isolation
                    if self.raw_input("Approve execution? [Y/n] ").strip().lower()[0] == "y":
                        self.update_output(await self.exec_tool(code))
                    else:
                        self.update_output("Rejected.")

            elif code[0] == '!' or code[0] == '<':
                return self._do_command(code)
            else:
                query = AnthropicQuery(EnvClient(), code.strip(), prefix="".join(self.chat_log))
                for message in query.stream():
                    self.update_output(message)
                if store_history and query.prompt_and_answer():
                    self.chat_log.append(query.prompt_and_answer())
        except KeyboardInterrupt:
            return {'status': 'abort', 'execution_count': self.execution_count}
        except Exception as error:
            self.process_output(error)
            error_content = {
                'ename': '',
                'evalue': str(error),
                'traceback': []
            }
            self.send_response(self.iopub_socket, 'error', error_content)

            error_content['execution_count'] = self.execution_count
            error_content['status'] = 'error'
            return error_content

        return {'status': 'ok', 'execution_count': self.execution_count,
                'payload': [], 'user_expressions': {}}

    def _do_command(self,code):
        status_ok = {'status': 'ok', 'execution_count': self.execution_count,
                     'payload': [], 'user_expressions': {}}
        
        match code.splitlines()[0]:
            case "!log":
                self.process_output("".join(self.chat_log))
                if len(code.splitlines()[1:]):
                    raise Exception("!log takes no input")
                return status_ok
            case "!reset":
                self.chat_log = [""]
                if len(code.splitlines()[1:]):
                    #TODO split on anthropic.HUMAN_PROMPT
                    prompt = "\n\n" + "\n".join(code.splitlines()[1:]).strip()
                    self.chat_log[0]=prompt
                lines = self.chat_log[0].count('\n')
                self.process_output(f"Reset! Prompt is {lines} lines.")
                return status_ok
            case "!nb" | "<!--":
                self.process_output("[Ignoring...]")
                return status_ok
            case _:
                raise Exception(f"Unknown command {code.splitlines()[0]}")
                
    def do_complete(self, code, cursor_pos):
        code = code[:cursor_pos]
        default = {'matches': [], 'cursor_start': 0,
                   'cursor_end': cursor_pos, 'metadata': dict(),
                   'status': 'ok'}

        #There are some interesting things that could be done here with prompt suggestion
        # but right now, no
        return default