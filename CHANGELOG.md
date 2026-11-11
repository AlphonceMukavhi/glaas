# Changelog

## Wayground Excel import
- New `wayground_import.py` reads the `.xlsx` file Wayground (Quizizz) exports, with no CSV conversion needed.
- Keeps the most complete attempt when a learner played more than once.
- Matches messy display names (initials, nicknames, digits used as letters) to the registered learner list, and reports any it cannot match.
- `learners` table gained a `full_name` column used only for this matching. The anonymous learner code is still the identifier everywhere else.
- Learner and score imports now accept `.xlsx` as well as `.csv`.

## Security
- No default password. The first researcher account is created from `GLAAS_ADMIN_EMAIL` / `GLAAS_ADMIN_PASSWORD`, or a random password is printed once.
- `SECRET_KEY` is read from the environment.
