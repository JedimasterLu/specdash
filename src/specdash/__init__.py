"""SpecDash: interactive processing of Andor Solis ``.asc`` spectra."""

from importlib.metadata import version

from specdash.io import AndorSpectrum, parse_asc, read_asc

__all__ = ["AndorSpectrum", "parse_asc", "read_asc"]
__version__ = version("specdash")
