"""eGov/HGATE fleet connectors, one module per surface.

eGov and HGATE are one vendor family read by the same v0 reader (``leggi_egov``),
so they live in one package — but each ``(platform × surface)`` pair is still its
own leaf class, named and versioned independently (I2).
"""
