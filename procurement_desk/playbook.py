"""Playbook loader: turns the markdown playbook into typed, immutable-by-convention policy data.

Nothing about a specific category, supplier or amendment is hard-coded in the engine; everything the
engine knows about Acme's rules comes from here, so a changed or extended playbook needs no code change.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from pathlib import Path


def _num(text: str) -> Fraction:
    cleaned = text.replace(",", "").replace("₹", "").replace("%", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not match:
        raise ValueError(f"No number in {text!r}")
    return Fraction(match.group(0))


def _field_value(text: str, label: str) -> str | None:
    match = re.search(rf"\*\*{re.escape(label)}:\*\*\s*(.+)", text, re.I)
    return match.group(1).strip() if match else None


def _singular(word: str) -> str:
    word = word.lower()
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


@dataclass(frozen=True)
class Category:
    key: str
    name: str
    normalized_unit: str
    gst_rate: Fraction
    target: Fraction
    walkaway: Fraction
    rounds: int
    beta: int
    approval_limit: Fraction
    period: str | None = None                                   # "year" / "month" for subscriptions
    sub_units: dict[str, Fraction] = field(default_factory=dict)   # {"ream": 10}: one box = 10 reams -> x10
    pack_size: dict[str, Fraction] = field(default_factory=dict)   # {"pack": 4}: a pack holds 4 units -> /4


@dataclass(frozen=True)
class Supplier:
    name: str
    status: str = "APPROVED"
    price_caps: dict[str, Fraction] = field(default_factory=dict)
    exchange_rates: dict[str, Fraction] = field(default_factory=dict)
    known: bool = True

    @property
    def blacklisted(self) -> bool:
        return self.status.startswith("BLACKLISTED")

    @property
    def probation(self) -> bool:
        return self.status.startswith("PROBATION")


@dataclass(frozen=True)
class Amendment:
    effective: date
    category_key: str
    field_name: str            # target_price | walk_away_price | approval_limit
    value: Fraction
    source: str


@dataclass(frozen=True)
class ResolvedValues:
    """The numbers in force for one thread, with provenance for the audit trail."""
    target: Fraction
    walkaway: Fraction
    approval_limit: Fraction
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class Issue:
    severity: str              # "error" | "warning"
    message: str


@dataclass
class Playbook:
    root: Path
    categories: dict[str, Category]
    suppliers: dict[str, Supplier]
    amendments: list[Amendment]
    exchange_rates: dict[str, Fraction]
    precedents: dict[str, list[str]]
    fingerprint: str
    load_issues: list[Issue] = field(default_factory=list)

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, root: str | Path) -> "Playbook":
        root = Path(root)
        candidates = (root, root / "playbook", root / "playbook" / "playbook", root / "dataset",
                      root / "dataset" / "playbook", root / "dataset" / "playbook" / "playbook")
        base = next((c for c in candidates if (c / "categories").is_dir()), None)
        if base is None:
            raise FileNotFoundError(f"Could not find playbook categories under {root}")
        issues: list[Issue] = []

        categories: dict[str, Category] = {}
        for path in sorted((base / "categories").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            name_match = re.search(r"^# Category:\s*(.+)$", text, re.M)
            name = name_match.group(1).strip() if name_match else path.stem.replace("-", " ").title()
            values = {k: _field_value(text, k) for k in (
                "Normalized unit", "GST rate", "Target price", "Walk-away price",
                "Negotiation rounds (R)", "Concession exponent (β)", "Approval limit")}
            if not all(values.values()):
                raise ValueError(f"Incomplete category file: {path}")
            unit = values["Normalized unit"] or ""
            lowered = unit.lower()
            period = "year" if "per year" in lowered else "month" if "per month" in lowered else None
            sub_units: dict[str, Fraction] = {}
            pack_size: dict[str, Fraction] = {}
            conversion = re.search(r"Pack conversion:\s*(.+)", text, re.I)
            if conversion:
                m = re.search(r"(?:one|a|1)\s+(\w+)\s*=\s*(\d+)\s+(\w+)", conversion.group(1), re.I)
                if m:      # "one box = 10 reams": a price quoted per ream is x10 per box
                    sub_units[_singular(m.group(3))] = Fraction(m.group(2))
                m = re.search(r"(?:a|one|1)\s+(\w+)\s+holds\s+(\d+)\s+(\w+)", conversion.group(1), re.I)
                if m:      # "a pack holds 4 fixtures": a price quoted per pack is /4 per fixture
                    pack_size[_singular(m.group(1))] = Fraction(m.group(2))
                if not sub_units and not pack_size:
                    issues.append(Issue("warning", f"{path.name}: unrecognised pack conversion {conversion.group(1)!r}"))
            categories[path.stem] = Category(
                key=path.stem, name=name, normalized_unit=unit, gst_rate=_num(values["GST rate"] or "") / 100,
                target=_num(values["Target price"] or ""), walkaway=_num(values["Walk-away price"] or ""),
                rounds=int(values["Negotiation rounds (R)"] or 0),
                beta=int(re.search(r"\d+", values["Concession exponent (β)"] or "")[0]),   # type: ignore[index]
                approval_limit=_num(values["Approval limit"] or ""),
                period=period, sub_units=sub_units, pack_size=pack_size)

        by_name = {c.name.lower(): c for c in categories.values()}

        suppliers: dict[str, Supplier] = {}
        for path in sorted((base / "suppliers").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            name_match = re.search(r"^# Supplier:\s*(.+)$", text, re.M)
            name = name_match.group(1).strip() if name_match else path.stem
            status_match = re.search(r"\*\*Status:\*\*\s*([^—\n]+)", text, re.I)
            status = status_match.group(1).strip().upper() if status_match else "APPROVED"
            if status.split()[0] not in {"APPROVED", "BLACKLISTED", "PROBATION"}:
                issues.append(Issue("warning", f"{path.name}: unrecognised status {status!r}; treated as approved"))
            caps: dict[str, Fraction] = {}
            rates: dict[str, Fraction] = {}
            for m in re.finditer(r"price cap for (.+?) of ₹([\d,\.]+) per .+?\(replaces the walk-away price\)", text, re.I):
                cat = by_name.get(m.group(1).strip().lower())
                if cat:
                    caps[cat.key] = _num(m.group(2))
                else:
                    issues.append(Issue("error", f"{path.name}: price cap for unknown category {m.group(1)!r}"))
            for m in re.finditer(r"invoices in ([A-Z]{3}) are converted at ₹([\d,\.]+) per \1", text, re.I):
                rates[m.group(1).upper()] = _num(m.group(2))
            for line in re.findall(r"\*\*Contract:\*\*\s*(.+)", text):
                if not re.search(r"price cap for|invoices in [A-Z]{3} are converted", line, re.I):
                    issues.append(Issue("warning", f"{path.name}: contract clause not understood: {line!r}"))
            suppliers[name.casefold()] = Supplier(name, status, caps, rates)

        amendments: list[Amendment] = []
        for path in sorted((base / "amendments").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            eff = re.search(r"\*\*Effective from:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
            change = re.search(r"\*\*Change:\*\*\s*(.+)", text)
            title = re.search(r"^# AMD-\d+:\s*(.+)$", text, re.M)
            if not (eff and change and title):
                raise ValueError(f"Could not parse amendment: {path}")
            cat = by_name.get(title.group(1).strip().lower())
            fm = re.search(r"(target price|walk-away price|approval limit) for .+? is now ₹([\d,\.]+)", change.group(1), re.I)
            if not cat or not fm:
                raise ValueError(f"Unrecognized amendment: {path}")
            amendments.append(Amendment(date.fromisoformat(eff.group(1)), cat.key,
                                        fm.group(1).lower().replace("-", "_").replace(" ", "_"),
                                        _num(fm.group(2)), path.stem))

        rates_table = {"USD": Fraction(845, 10), "EUR": Fraction(91), "GBP": Fraction(106)}
        currency_file = base / "policies" / "units-and-currency.md"
        if currency_file.exists():
            found = re.findall(r"\|\s*([A-Z]{3})\s*\|\s*₹?([\d.]+)\s*\|", currency_file.read_text(encoding="utf-8"))
            if found:
                rates_table = {cur: Fraction(rate) for cur, rate in found}

        precedents: dict[str, list[str]] = {}
        for path in sorted((base / "precedents").glob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            m = re.search(r"^# Precedent P-\d+ — (.+)$", text, re.M)
            cat = by_name.get(m.group(1).strip().lower()) if m else None
            precedents.setdefault(cat.key if cat else "general", []).append(text)

        digest = hashlib.sha256()
        for path in sorted(base.rglob("*.md")):
            digest.update(str(path.relative_to(base)).encode())
            digest.update(path.read_bytes())
        return cls(base, categories, suppliers, amendments, rates_table, precedents, digest.hexdigest()[:16], issues)

    # ------------------------------------------------------------------ lookups
    def supplier_for(self, name: str) -> Supplier:
        return self.suppliers.get(name.casefold()) or Supplier(name=name, known=False)

    def values_for(self, category_key: str, supplier_name: str, on_date: date | str) -> ResolvedValues:
        """Target, walk-away and approval limit in force on a date, with provenance.

        Order (policies/decision-procedure.md): category page -> every amendment effective on/before the
        thread date (later effective date wins) -> supplier contract price cap replaces the walk-away price.
        """
        if isinstance(on_date, str):
            on_date = date.fromisoformat(on_date)
        cat = self.categories[category_key]
        target, walk, limit = cat.target, cat.walkaway, cat.approval_limit
        why = [f"category page {category_key}"]
        applicable = sorted((a for a in self.amendments if a.category_key == category_key and a.effective <= on_date),
                            key=lambda a: a.effective)
        for a in applicable:
            if a.field_name == "target_price":
                target = a.value
            elif a.field_name == "walk_away_price":
                walk = a.value
            elif a.field_name == "approval_limit":
                limit = a.value
            why.append(f"{a.source} (effective {a.effective}): {a.field_name}")
        cap = self.supplier_for(supplier_name).price_caps.get(category_key)
        if cap is not None:
            walk = cap
            why.append(f"supplier contract price cap replaces walk-away price")
        return ResolvedValues(target, walk, limit, tuple(why))

    def fx_rate(self, supplier_name: str, currency: str) -> tuple[Fraction, str] | None:
        """(INR per unit, source). A supplier contract rate replaces the table rate for that currency."""
        currency = currency.upper()
        contract = self.supplier_for(supplier_name).exchange_rates.get(currency)
        if contract is not None:
            return contract, "supplier contract rate"
        table = self.exchange_rates.get(currency)
        return (table, "playbook table rate") if table is not None else None

    # ------------------------------------------------------------------ validation
    def validate(self) -> list[Issue]:
        """Consistency checks on the playbook itself. Run in CI and before deploying a playbook change."""
        issues = list(self.load_issues)
        for c in self.categories.values():
            if c.target <= 0 or c.walkaway < c.target:
                issues.append(Issue("error", f"{c.key}: walk-away must be >= target > 0"))
            if c.rounds < 2:
                issues.append(Issue("error", f"{c.key}: needs at least 2 negotiation rounds"))
            if c.beta < 1:
                issues.append(Issue("error", f"{c.key}: concession exponent must be >= 1"))
            if c.approval_limit <= 0 or not 0 <= c.gst_rate < 1:
                issues.append(Issue("error", f"{c.key}: invalid approval limit or GST rate"))
        seen: dict[tuple[str, str, date], Fraction] = {}
        for a in self.amendments:
            key = (a.category_key, a.field_name, a.effective)
            if key in seen and seen[key] != a.value:
                issues.append(Issue("error", f"{a.source}: conflicts with another amendment on the same date"))
            seen[key] = a.value
        for cat in self.categories.values():
            dates = sorted({a.effective for a in self.amendments if a.category_key == cat.key})
            for when in dates:
                v = self.values_for(cat.key, "", when)
                if v.walkaway < v.target:
                    issues.append(Issue("error", f"{cat.key}: walk-away below target after amendment on {when}"))
        for s in self.suppliers.values():
            for key, cap in s.price_caps.items():
                if cap <= 0:
                    issues.append(Issue("error", f"{s.name}: non-positive price cap for {key}"))
        return issues
