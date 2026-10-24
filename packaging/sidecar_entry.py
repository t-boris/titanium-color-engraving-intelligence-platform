"""The entry point of the packaged core (PyInstaller, ``sidecar.spec``): the console command as the desktop shell starts it."""
import multiprocessing
import sys

from titanium_platform.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()          # a frozen core on Windows must not start a second copy of itself from worker processes
    sys.exit(main())
