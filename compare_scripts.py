#!/usr/bin/env python3
"""
Compare scripts: scripts_previous (backup) vs scripts (new).
Run after generating new scripts: python compare_scripts.py
"""

from pathlib import Path

OUTPUT = Path(__file__).parent / "output"
OLD = OUTPUT / "scripts_previous"
NEW = OUTPUT / "scripts"


def main():
    if not OLD.is_dir():
        print("Directory output/scripts_previous (backup) missing. Copy current scripts there first.")
        return
    if not NEW.is_dir():
        print("Directory output/scripts missing.")
        return

    old_files = sorted(OLD.glob("*.txt"))
    if not old_files:
        print("No .txt files in scripts_previous.")
        return

    print("Comparison: scripts_previous (old) vs scripts (new)\n")
    print(f"{'File':<60} {'Old lines':>12} {'New lines':>12} {'Old chars':>12} {'New chars':>12}  Note")
    print("-" * 120)

    for old_path in old_files:
        name = old_path.name
        new_path = NEW / name
        if not new_path.exists():
            print(f"{name:<60} {'—':>12} {'(missing)':>12} {'—':>12} {'—':>12}  no new file")
            continue

        try:
            old_text = old_path.read_text(encoding="utf-8")
            new_text = new_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            print(f"{name}: encoding error - {e}")
            continue

        old_lines = len(old_text.splitlines())
        new_lines = len(new_text.splitlines())
        old_chars = len(old_text)
        new_chars = len(new_text)

        if new_lines >= old_lines and new_chars >= old_chars:
            note = "new longer or equal"
        elif new_lines < old_lines and new_chars < old_chars:
            note = "new shorter"
        else:
            note = "mixed"

        print(f"{name[:58]:<60} {old_lines:>12} {new_lines:>12} {old_chars:>12} {new_chars:>12}  {note}")

    print("-" * 120)
    print("\nBackup (old): output/scripts_previous/")
    print("Current (new): output/scripts/")


if __name__ == "__main__":
    main()
