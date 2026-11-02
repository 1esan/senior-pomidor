"""Deduplicate discovered vacancy IDs across search queries in one run."""
class VacancyRunClaims:
    def __init__(self):
        self._seen = set()

    def claim(self, vacancy):
        raw = vacancy.get('id')
        if raw is None:
            return True
        key = str(raw)
        if not key:
            return True
        if key in self._seen:
            return False
        self._seen.add(key)
        return True
