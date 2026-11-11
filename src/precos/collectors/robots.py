"""Leitor mínimo de robots.txt (o urllib.robotparser não entende `*` e `$` nos caminhos, que a KaBuM usa)."""
from __future__ import annotations

import re


class Robots:
    def __init__(self, text: str, agent: str):
        token = agent.split("/")[0].strip().lower()
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, _, value = (p.strip() for p in line.partition(":"))
            key = key.lower()
            if key == "user-agent":
                if in_rules:
                    groups.append((agents, rules))
                    agents, rules, in_rules = [], [], False
                agents.append(value.lower())
            elif key in ("allow", "disallow"):
                in_rules = True
                rules.append((key == "allow", value))
        if agents:
            groups.append((agents, rules))
        specific = [r for a, r in groups if any(x != "*" and x in token for x in a)]
        generic = [r for a, r in groups if "*" in a]
        self.rules = [rule for g in (specific or generic) for rule in g]

    @staticmethod
    def _regex(pattern: str) -> re.Pattern:
        anchored = pattern.endswith("$")
        body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
        return re.compile(body + ("$" if anchored else ""))

    def allowed(self, path_and_query: str) -> bool:
        """A regra mais longa vence; em empate, Allow vence. Disallow vazio não bloqueia nada."""
        best_len, verdict = -1, True
        for allow, pattern in self.rules:
            if not pattern:
                continue
            if self._regex(pattern).match(path_and_query) and (len(pattern) > best_len or (len(pattern) == best_len and allow)):
                best_len, verdict = len(pattern), allow
        return verdict
