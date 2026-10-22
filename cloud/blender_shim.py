"""Stand-in for the blender binary when the Linux tarball cannot start on a cloud box (2026-10-21): runs the
--python script under the bpy wheel instead. ms._blender sends
    blender -b --factory-startup -Y --python-exit-code 1 --python <script> -- <args>
and every Master Smith Blender script reads its arguments after the "--". An exception leaves with exit 1, which
is what --python-exit-code 1 would do. Install the wheel into the venv first: pip install bpy==5.2.2 (Python 3.13);
then BLENDER_BIN=<repo>/cloud/blender."""
import runpy
import sys

argv = sys.argv[1:]
if "--python" not in argv:
    sys.exit("blender_shim: no --python <script> in %r" % argv)
script = argv[argv.index("--python") + 1]
rest = argv[argv.index("--") + 1:] if "--" in argv else []
import bpy  # noqa: E402,F401  the wheel; importing it is the factory start-up

sys.argv = [script, "--"] + rest
runpy.run_path(script, run_name="__main__")
