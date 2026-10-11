"""Process-wide web state shared between the app lifespan and the routers."""

#: Set by the lifespan when first boot migrated the legacy single-slot layout into a
#: "Default" workspace. `GET /api/config` reports it once so the UI can say where the
#: files went, then clears it.
migrated_from_legacy = False

#: Set by `infra/desktop_main.py` before the server starts: the app runs on the person's
#: own machine, so it may open files in their word processor (Edit layout in Word).
desktop = False
