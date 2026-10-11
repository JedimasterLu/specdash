"""SpecDash: interactive processing of Andor Solis ``.asc`` spectra."""

from specdash.io import AndorSpectrum, parse_asc, read_asc

__all__ = ["AndorSpectrum", "parse_asc", "read_asc"]
__version__ = "0.1.0"
