"""Process-wide web state shared between the app lifespan and the routers."""

#: Set by the lifespan when first boot migrated the legacy single-slot layout; the
#: config route reports it once, then clears it.
migrated_from_legacy = False
