# -*- coding: utf-8 -*-
"""
Internationalisation helpers with graceful fallback to .po catalogues.

Flask-Babel expects compiled ``messages.mo`` files. Some deployment
environments (including the Codex sandbox) forbid writing binary files at
runtime, which means only ``messages.po`` may be present.  ``PoFallbackDomain``
mirrors the default domain behaviour but transparently compiles the .po data
in-memory whenever the .mo file is missing. This keeps translations working
without requiring an on-disk compilation step.
"""

from __future__ import annotations

import os
from io import BytesIO
from typing import Iterable

from babel.messages import mofile, pofile
from flask_babel import Domain, _get_current_context, get_locale, support


class PoFallbackDomain(Domain):
    """Load translations, compiling .po files in-memory when .mo is absent."""

    def _load_catalog(self, directory: str, locale: str, domain: str):
        """
        Attempt to load the compiled catalogue; fall back to building it
        from the source .po file when necessary.
        """

        try:
            return support.Translations.load(directory, [locale], domain)
        except OSError:
            po_path = os.path.join(directory, str(locale), "LC_MESSAGES", f"{domain}.po")
            if not os.path.exists(po_path):
                raise
            with open(po_path, "r", encoding="utf-8") as handle:
                catalog = pofile.read_po(handle)
            buffer = BytesIO()
            mofile.write_mo(buffer, catalog)
            buffer.seek(0)
            return support.Translations(fp=buffer)

    def _iter_domains(self) -> Iterable[tuple[str, str]]:
        """
        Yield ``(directory, domain)`` tuples honouring multi-domain setups.
        """

        directories = list(self.translation_directories)
        if len(self.domain) == 1:
            for directory in directories:
                yield directory, self.domain[0]
        else:
            for directory, domain in zip(directories, self.domain):
                yield directory, domain

    def get_translations(self):
        ctx = _get_current_context()
        if ctx is None:
            return support.NullTranslations()

        cache = self.get_translations_cache(ctx)
        locale = get_locale()
        cache_key = (str(locale), self.domain[0])
        if cache_key in cache:
            return cache[cache_key]

        translations = support.Translations()
        for directory, domain in self._iter_domains():
            try:
                catalog = self._load_catalog(directory, locale, domain)
            except OSError:
                continue
            translations.merge(catalog)
            if hasattr(catalog, "plural"):
                translations.plural = catalog.plural

        cache[cache_key] = translations
        return translations
