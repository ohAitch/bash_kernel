from ipykernel.kernelbase import Kernel

import anthropic

import os
import re

__version__ = '0.0.1'

version_pat = re.compile(r'version (\d+(\.\d+)+)')

from .display import extract_contents

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

    def __init__(self, **kwargs):
        Kernel.__init__(self, **kwargs)
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

    def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False):
        self.silent = silent
        default = {'status': 'ok', 'execution_count': self.execution_count,
                    'payload': [], 'user_expressions': {}}
        if not code.strip():
            return default

        try:
            if code[0] == '!' or code[0] == '<':
                match code.splitlines()[0]:
                    case "!log":
                        self.process_output("\n".join(self.chat_log))
                        if len(code.splitlines()[1:]):
                            raise Exception("!log takes no input")
                        return default
                    case "!reset":
                        self.chat_log = []
                        if len(code.splitlines()[1:]):
                            #TODO split on anthropic.HUMAN_PROMPT
                            prompt = "\n\n" + "\n".join(code.splitlines()[1:]).strip()
                            self.chat_log.append(prompt)
                        lines = (self.chat_log or [""])[0].count('\n')
                        self.process_output(f"Reset! Prompt is {lines} lines.")
                        return default
                    case "!nb" | "<!--":
                        self.process_output("[Ignoring...]")
                        return default
                    case _:
                        raise Exception(f"Unknown command {code.splitlines()[0]}")

            client = anthropic.Client(os.environ["ANTHROPIC_API_KEY"])
            max_tokens_to_sample = 500 #TODO configure max_tokens model etc
            prompt_entry = f"{anthropic.HUMAN_PROMPT} {code.strip()}{anthropic.AI_PROMPT}"
            prompt = "\n".join(self.chat_log + [prompt_entry])
            stream = client.completion_stream(
                prompt=prompt, max_tokens_to_sample=max_tokens_to_sample,
                stop_sequences=[anthropic.HUMAN_PROMPT],
                model="claude-instant-v1",
            )
            completion = None
            for message in stream:
                stdout_text = {'name': 'stdout', 'text': message['completion']}
                self.send_response(self.iopub_socket, 'clear_output', {'wait': True})
                self.send_response(self.iopub_socket, 'stream', stdout_text)
                completion = message['completion']
            if store_history and completion is not None:
                self.chat_log.append(prompt_entry + completion)
            #MAYFIX handle images html etc
            #self.process_output(result['completion'])
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

    def do_complete(self, code, cursor_pos):
        code = code[:cursor_pos]
        default = {'matches': [], 'cursor_start': 0,
                   'cursor_end': cursor_pos, 'metadata': dict(),
                   'status': 'ok'}

        #There are some interesting things that could be done here with prompt suggestion
        # but right now, no
        return default