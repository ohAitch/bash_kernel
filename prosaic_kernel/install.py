import json
import os
import sys
import argparse

from jupyter_client.kernelspec import KernelSpecManager
from IPython.utils.tempdir import TemporaryDirectory

kernel_json = {"argv":[sys.executable,"-m","prosaic_kernel", "-f", "{connection_file}"],
 "display_name":"prosaic",
 "language":"markdown",
 "codemirror_mode":"markdown",
 "env":{"PS1": "$"}
}

def install_my_kernel_spec(user=True, prefix=None, name='prosaic'):
    with TemporaryDirectory() as td:
        os.chmod(td, 0o755) # Starts off as 700, not user readable
        with open(os.path.join(td, 'kernel.json'), 'w') as f:
            json.dump(kernel_json, f, sort_keys=True)
        # TODO: Copy resources once they're specified

        print('Installing IPython kernel spec')
        KernelSpecManager().install_kernel_spec(td, name, user=user, prefix=prefix)

def _is_root():
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False # assume not an admin on non-Unix platforms

def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Install KernelSpec for Prosaic Kernel'
    )
    prefix_locations = parser.add_mutually_exclusive_group()

    prefix_locations.add_argument(
        '--user',
        help='Install KernelSpec in user\'s home directory',
        action='store_true'
    )
    prefix_locations.add_argument(
        '--sys-prefix',
        help='Install KernelSpec in sys.prefix. Useful in conda / virtualenv',
        action='store_true',
        dest='sys_prefix'
    )
    prefix_locations.add_argument(
        '--prefix',
        help='Install KernelSpec in this prefix',
        default=None
    )

    parser.add_argument(
        '--variant',
        help='Prosaic kernel mode (chat or validator)',
        default='chat'
    )

    args = parser.parse_args(argv)

    user = False
    prefix = None
    if args.sys_prefix:
        prefix = sys.prefix
    elif args.prefix:
        prefix = args.prefix
    elif args.user or not _is_root():
        user = True

    #XXX reify feature flag as separate kernels
    match args.variant:
        case 'chat':
            install_my_kernel_spec(user=user, prefix=prefix)
        case 'validator':
            kernel_json["language"] = kernel_json["codemirror_mode"] = "python"
            kernel_json["display_name"] = "prosaic (validator)"
            kernel_json["env"]["PROSAIC_VALIDATION_MODE"] = "Y"
            install_my_kernel_spec(user=user, prefix=prefix, name='prosaic-validator')
    

if __name__ == '__main__':
    if not os.environ.get("ANTHROPIC_API_KEY"):
        #TODO support %env and other magics, so this could also be loaded at runtime
        print("ANTHROPIC_API_KEY unset or blank. Please set it to your API key.")
        sys.exit(1)
    kernel_json["env"]["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    main()
