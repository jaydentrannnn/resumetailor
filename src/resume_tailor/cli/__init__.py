"""The `tailor.py` command line: `args` parses flags, `run` wires one invocation.

    python tailor.py --jd jd.txt [--out output/tailored.docx] [--pages 1]
                     [--experience 3] [--projects 2] [--template ...]
    python -m resume_tailor.cli --jd jd.txt   # same thing, without the root shim
"""
