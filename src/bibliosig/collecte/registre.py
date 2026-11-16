"""Registre des notices collectées : une ligne par notice, avec tous ses couples."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


class RegistreNotices:
    """Garde, pour chaque identifiant, la première notice vue et ses couples A × B.

    Paramètres
    ----------
    champ_identifiant : str
    """

    def __init__(self, champ_identifiant: str) -> None:
        self.champ_identifiant = champ_identifiant
        self.notices: dict[str, dict[str, Any]] = {}
        self.couples: dict[str, list[str]] = {}

    def enregistrer(self, identifiant: str, notice: dict[str, Any], libelle_a: str, libelle_b: str) -> None:
        """Ajoute une notice trouvée par un couple de concepts.

        Paramètres
        ----------
        identifiant : str
        notice : dict
        libelle_a, libelle_b : str
        """
        couple = f"{libelle_a} × {libelle_b}"
        if identifiant not in self.notices:
            self.notices[identifiant] = notice
            self.couples[identifiant] = [couple]
        elif couple not in self.couples[identifiant]:
            self.couples[identifiant].append(couple)

    def ecrire(self, chemin: Path, champs: list[str]) -> int:
        """Écrit le fichier dédoublonné : identifiant, couples, nombre de couples, champs.

        Paramètres
        ----------
        chemin : Path
        champs : list of str
            Champs de notice, identifiant compris.

        Renvoie
        -------
        int
            Nombre de notices.
        """
        entetes = [self.champ_identifiant, "combinaisons_AB", "nb_combinaisons"] + [
            champ for champ in champs if champ != self.champ_identifiant
        ]
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("w", newline="", encoding="utf-8-sig") as flux:
            ecrivain = csv.DictWriter(flux, fieldnames=entetes, extrasaction="ignore")
            ecrivain.writeheader()
            for identifiant, notice in self.notices.items():
                couples = self.couples[identifiant]
                ecrivain.writerow(
                    {
                        **notice,
                        self.champ_identifiant: identifiant,
                        "combinaisons_AB": " || ".join(couples),
                        "nb_combinaisons": len(couples),
                    }
                )
        return len(self.notices)
