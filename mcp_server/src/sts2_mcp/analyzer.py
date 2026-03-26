"""Combat state analyzer for STS2.

Evaluates current combat and returns advisory data:
survival checks, lethal detection, potion recommendations,
synergy flags, and energy efficiency notes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_MOVE_SUFFIX_RE = re.compile(r"(_MOVE|_\d+)$", re.IGNORECASE)
_CARD_NAME_RE = re.compile(r"^([^[：:]+)")
_MULTIPLIER_RE = re.compile(r"^(\w+)\*(\d+)")


def _normalize_key(raw: str) -> str:
    stripped = _MOVE_SUFFIX_RE.sub("", raw.strip())
    return re.sub(r"[_\s]+", "", stripped).lower()


def _parse_card_name(line: str) -> str:
    m = _MULTIPLIER_RE.match(line)
    if m:
        return m.group(1).strip()
    m = _CARD_NAME_RE.match(line)
    return m.group(1).strip() if m else line.strip()


class CombatAnalyzer:
    def __init__(self, game_data_dir: str | Path) -> None:
        game_data_dir = Path(game_data_dir)
        self._monsters = self._load_monsters(game_data_dir / "monsters.json")
        self._cards = self._load_cards(game_data_dir / "cards.json")
        self._potions = self._load_potions(game_data_dir / "potions.json")

    @staticmethod
    def _load_monsters(path: Path) -> dict[str, dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        lookup: dict[str, dict[str, Any]] = {}
        for m in data:
            lookup[m["id"]] = m
            lookup[m["name"].lower()] = m
        return lookup

    @staticmethod
    def _load_cards(path: Path) -> dict[str, dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        lookup: dict[str, dict[str, Any]] = {}
        for c in data:
            lookup[c["id"]] = c
            lookup[c["name"].lower()] = c
        return lookup

    @staticmethod
    def _load_potions(path: Path) -> dict[str, dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        lookup: dict[str, dict[str, Any]] = {}
        for p in data:
            lookup[p["id"]] = p
            lookup[p["name"].lower()] = p
        return lookup

    def _lookup_monster(self, enemy: dict[str, Any]) -> dict[str, Any] | None:
        name = (enemy.get("name") or "").strip()
        if not name:
            return None
        return self._monsters.get(name.lower())

    def _lookup_card(self, card_name: str) -> dict[str, Any] | None:
        return self._cards.get(card_name.lower())

    def _estimate_intent_damage(self, monster_data: dict[str, Any], intent: str) -> int | None:
        dmg_values = monster_data.get("damage_values")
        if not dmg_values:
            return None

        norm_intent = _normalize_key(intent)
        for key, val in dmg_values.items():
            if _normalize_key(key) == norm_intent:
                return val.get("normal", 0)

        # Broader fuzzy: check if intent contains the key or vice versa
        for key, val in dmg_values.items():
            norm_key = _normalize_key(key)
            if norm_key in norm_intent or norm_intent in norm_key:
                return val.get("normal", 0)

        return None

    def evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        combat = state.get("combat")
        if not combat:
            return {"error": "not_in_combat", "message": "No active combat state found."}

        player = combat.get("player", {})
        enemies = combat.get("enemies", [])
        hand = combat.get("hand", [])

        # Parse player HP
        hp_str = player.get("hp", "0/0")
        hp_parts = str(hp_str).split("/")
        current_hp = int(hp_parts[0]) if hp_parts[0].isdigit() else 0
        max_hp = int(hp_parts[1]) if len(hp_parts) > 1 and hp_parts[1].isdigit() else current_hp
        player_block = player.get("block", 0) or 0
        energy = player.get("energy", 0) or 0

        # Parse run info for potions
        run = state.get("run", {})
        potions_raw = run.get("potions") or combat.get("potions") or []

        # Analyze each alive enemy
        enemy_analyses = []
        for enemy in enemies:
            if not enemy.get("alive", True):
                continue
            enemy_analyses.append(self._analyze_enemy(enemy))

        # Primary target: first alive enemy (most fights are single-enemy)
        primary = enemy_analyses[0] if enemy_analyses else None

        survival = self._survival_check(current_hp, max_hp, player_block, enemy_analyses)
        lethal = self._lethal_check(hand, energy, enemy_analyses, potions_raw)
        potions = self._potion_recommendations(potions_raw, current_hp, max_hp, survival, lethal)
        synergies = self._synergy_check(hand, enemy_analyses)
        energy_info = self._energy_check(hand, energy)
        priority = self._classify_priority(survival, lethal)

        return {
            "survival": survival,
            "lethal": lethal,
            "potions": potions,
            "synergies": synergies,
            "energy": energy_info,
            "priority": priority,
        }

    def _analyze_enemy(self, enemy: dict[str, Any]) -> dict[str, Any]:
        name = enemy.get("name", "Unknown")
        hp_str = str(enemy.get("hp", "0/0"))
        hp_parts = hp_str.split("/")
        current_hp = int(hp_parts[0]) if hp_parts[0].isdigit() else 0
        max_hp = int(hp_parts[1]) if len(hp_parts) > 1 and hp_parts[1].isdigit() else current_hp
        block = enemy.get("block", 0) or 0
        intent = enemy.get("intent", "")

        monster_data = self._lookup_monster(enemy)
        estimated_damage = None
        damage_known = False
        if monster_data and intent:
            estimated_damage = self._estimate_intent_damage(monster_data, intent)
            damage_known = estimated_damage is not None

        return {
            "name": name,
            "index": enemy.get("i", 0),
            "hp": current_hp,
            "max_hp": max_hp,
            "block": block,
            "intent": intent,
            "estimated_damage": estimated_damage,
            "damage_known": damage_known,
        }

    def _survival_check(
        self,
        player_hp: int,
        max_hp: int,
        player_block: int,
        enemies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_incoming = 0
        unknown_intents = []
        for e in enemies:
            if e["estimated_damage"] is not None:
                total_incoming += e["estimated_damage"]
            elif e["intent"]:
                unknown_intents.append(f"{e['name']}:{e['intent']}")

        damage_after_block = max(0, total_incoming - player_block)
        lethal = damage_after_block >= player_hp
        hp_percent = (player_hp / max_hp * 100) if max_hp > 0 else 0

        return {
            "safe": not lethal and not unknown_intents,
            "player_hp": player_hp,
            "max_hp": max_hp,
            "hp_percent": round(hp_percent, 1),
            "player_block": player_block,
            "incoming_damage": total_incoming,
            "damage_after_block": damage_after_block,
            "lethal": lethal,
            "unknown_intents": unknown_intents,
            "enemies": [
                {"name": e["name"], "intent": e["intent"], "damage": e["estimated_damage"]}
                for e in enemies
            ],
        }

    def _lethal_check(
        self,
        hand: list[dict[str, Any]],
        energy: int,
        enemies: list[dict[str, Any]],
        potions_raw: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # Estimate total damage from hand
        hand_damage = 0
        energy_remaining = energy
        attack_count = 0

        playable_attacks = []
        for card in hand:
            if not card.get("playable", False):
                continue
            line = card.get("line", "")
            card_name = _parse_card_name(line)
            card_data = self._lookup_card(card_name)
            if card_data and card_data.get("type") == "Attack" and card_data.get("damage"):
                cost = card_data.get("cost", 1) or 0
                dmg = card_data["damage"]
                hits = card_data.get("hit_count") or 1
                playable_attacks.append({
                    "name": card_name,
                    "cost": cost,
                    "damage": dmg,
                    "hits": hits,
                    "total": dmg * hits,
                    "index": card.get("i"),
                })

        # Sort by damage efficiency (damage per energy, 0-cost first)
        playable_attacks.sort(key=lambda a: (a["cost"], -a["total"]))

        for atk in playable_attacks:
            if energy_remaining >= atk["cost"]:
                energy_remaining -= atk["cost"]
                hand_damage += atk["total"]
                attack_count += 1

        # Estimate potion damage
        potion_damage = 0
        strength_bonus = 0
        for p in potions_raw:
            if not isinstance(p, dict):
                continue
            if not p.get("usable", False):
                continue
            p_line = p.get("line", "").lower()
            if "fire potion" in p_line:
                potion_damage += 20
            elif "explosive" in p_line:
                potion_damage += 10
            elif "strength potion" in p_line:
                strength_bonus += 2

        # Strength bonus applies to each attack
        strength_damage = strength_bonus * attack_count
        total_available = hand_damage + potion_damage + strength_damage

        # Check against each enemy
        per_enemy = []
        for e in enemies:
            effective_hp = e["hp"] + e["block"]
            killable = total_available >= effective_hp
            killable_without_potions = hand_damage >= effective_hp
            per_enemy.append({
                "name": e["name"],
                "hp": e["hp"],
                "block": e["block"],
                "effective_hp": effective_hp,
                "killable": killable,
                "killable_without_potions": killable_without_potions,
            })

        any_killable = any(e["killable"] for e in per_enemy)
        all_killable = all(e["killable"] for e in per_enemy)

        return {
            "possible": all_killable,
            "any_enemy_killable": any_killable,
            "estimated_hand_damage": hand_damage,
            "estimated_potion_damage": potion_damage,
            "strength_bonus_damage": strength_damage,
            "total_available": total_available,
            "attack_count": attack_count,
            "energy_remaining": energy_remaining,
            "enemies": per_enemy,
        }

    def _potion_recommendations(
        self,
        potions_raw: list[dict[str, Any]],
        current_hp: int,
        max_hp: int,
        survival: dict[str, Any],
        lethal: dict[str, Any],
    ) -> list[dict[str, Any]]:
        hp_percent = survival.get("hp_percent", 100)
        is_lethal_incoming = survival.get("lethal", False)
        can_kill = lethal.get("possible", False)
        any_killable = lethal.get("any_enemy_killable", False)

        results = []
        for p in potions_raw:
            if not isinstance(p, dict):
                continue
            p_line = p.get("line", "")
            usable = p.get("usable", False)
            index = p.get("i")

            if not usable or not p_line or p_line.endswith("空"):
                continue

            # Extract potion name from line (format: "0: Fire Potion：CombatOnly")
            name_match = re.search(r"\d+:\s*(.+?)(?:：|$)", p_line)
            name = name_match.group(1).strip() if name_match else p_line

            rec = "hold"
            reason = "no urgent need"

            if "fire potion" in p_line.lower() or "explosive" in p_line.lower():
                if can_kill:
                    rec = "use_now"
                    reason = "enables lethal this turn"
                elif is_lethal_incoming:
                    rec = "use_now"
                    reason = "about to die, maximize damage output"
                elif hp_percent < 25 and any_killable:
                    rec = "use_now"
                    reason = "critically low HP, burst to finish"

            elif "strength potion" in p_line.lower():
                if can_kill or (hp_percent < 25 and any_killable):
                    rec = "use_now"
                    reason = "enables or assists lethal this turn"
                elif is_lethal_incoming:
                    rec = "use_now"
                    reason = "about to die, maximize damage output"

            elif "block potion" in p_line.lower():
                if is_lethal_incoming:
                    rec = "use_now"
                    reason = "incoming damage is lethal, block to survive"

            elif "blood potion" in p_line.lower() or "regen" in p_line.lower():
                if hp_percent < 30:
                    rec = "use_now"
                    reason = "critically low HP"

            results.append({
                "index": index,
                "name": name,
                "recommendation": rec,
                "reason": reason,
            })

        return results

    def _synergy_check(
        self,
        hand: list[dict[str, Any]],
        enemies: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        synergies: list[dict[str, Any]] = []

        # Parse hand card names
        hand_card_names = []
        for card in hand:
            line = card.get("line", "")
            name = _parse_card_name(line)
            hand_card_names.append(name.lower())

        # Check for vulnerability-related synergies
        # We can't directly read enemy powers from the compact state,
        # but we can flag cards that apply or benefit from vulnerability
        vuln_appliers = []
        vuln_beneficiaries = []

        for card in hand:
            line = card.get("line", "").lower()
            name = _parse_card_name(card.get("line", ""))
            if "vulnerable" in line:
                vuln_appliers.append(name)
            if "if the enemy is vulnerable" in line or "if vulnerable" in line:
                vuln_beneficiaries.append(name)

        if vuln_appliers and vuln_beneficiaries:
            synergies.append({
                "type": "vulnerability_combo",
                "appliers": vuln_appliers,
                "beneficiaries": vuln_beneficiaries,
                "note": f"Play {vuln_appliers[0]} first, then {vuln_beneficiaries[0]} for bonus effect",
            })

        # Check for cost reduction (Stomp-like)
        for card in hand:
            line = card.get("line", "").lower()
            name = _parse_card_name(card.get("line", ""))
            if "costs" in line and "less" in line and "attack" in line:
                synergies.append({
                    "type": "cost_reduction",
                    "card": name,
                    "note": "Play other attacks first to reduce this card's cost",
                })

        # Check for strength-this-turn cards
        for card in hand:
            line = card.get("line", "").lower()
            name = _parse_card_name(card.get("line", ""))
            if "strength this turn" in line:
                synergies.append({
                    "type": "temporary_strength",
                    "card": name,
                    "note": "Play this early to boost subsequent attacks this turn",
                })

        return synergies

    def _energy_check(
        self,
        hand: list[dict[str, Any]],
        energy: int,
    ) -> dict[str, Any]:
        zero_cost: list[str] = []
        cost_reduction: dict[str, str] = {}
        total_playable_cost = 0

        for card in hand:
            if not card.get("playable", False):
                continue
            line = card.get("line", "")
            name = _parse_card_name(line)
            card_data = self._lookup_card(name)
            cost = card_data.get("cost", 1) if card_data else 1

            if cost == 0:
                zero_cost.append(name)
            total_playable_cost += cost or 0

            if "costs" in line.lower() and "less" in line.lower():
                cost_reduction[name] = line.split("：")[-1].strip() if "：" in line else "dynamic cost"

        return {
            "total_energy": energy,
            "total_playable_cost": total_playable_cost,
            "can_play_all": total_playable_cost <= energy,
            "zero_cost_cards": zero_cost,
            "cost_reduction": cost_reduction,
        }

    def _classify_priority(
        self,
        survival: dict[str, Any],
        lethal: dict[str, Any],
    ) -> str:
        if lethal.get("possible"):
            return "LETHAL"
        if survival.get("lethal"):
            return "SURVIVE"
        if survival.get("hp_percent", 100) < 25:
            return "SURVIVE"
        return "DEFAULT"
