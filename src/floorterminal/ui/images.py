"""Composite static identity images in memory, not via X11 drawable readback."""

import tkinter as tk


def opaque_photo(source, background, master):
    """Preserve smooth edges without per-frame partial-alpha display reads.

    Composition is a one-time in-memory Tk operation. The source asset is not
    changed; the result is opaque and belongs to the same Tcl interpreter.
    """
    result = tk.PhotoImage(master=master, width=source.width(), height=source.height())
    result.put(background, to=(0, 0, source.width(), source.height()))
    result.tk.call(str(result), "copy", str(source), "-compositingrule", "overlay")
    # PPM has no alpha channel. Re-import also clears Tk's model-level complex
    # alpha flag, which can survive an otherwise opaque in-memory composition.
    rgb = result.tk.call(str(result), "data", "-format", "ppm")
    return tk.PhotoImage(master=master, data=rgb, format="ppm")
