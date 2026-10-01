# Journal de validation

## 2026-10-01 — État initial

- `DOCUMENT_MAITRE.md`, `ROADMAP.md` et `VALIDATION_LOG.md` absents au début de session ; création du maître explicitement autorisée par l'utilisateur.
- `git status` et `git log --oneline -20` : indisponibles car dossier non initialisé en dépôt Git.
- Aucun test fonctionnel ou déploiement confirmé à ce stade.
- La demande d'API externe a été retirée par l'utilisateur ; seul Ollama local est dans la portée.

## 2026-10-01 — Préparation et contrôles

- L'API locale `GET /api/tags` a retourné cinq modèles installés ; le sélecteur utilise cette même API.
- `python -m unittest discover -s tests -v` : trois tests réussis.
- `python -m py_compile app.py` : réussi.
- `uvx ruff check app.py tests` : réussi.
- L'interface Tkinter s'est ouverte puis fermée sans erreur lors d'un lancement court.
- Génération réelle par `POST /api/chat` avec `qwen3.5:2b` : réponse reçue et flux terminé sans erreur.
- Le choix dans la fenêtre n'a pas été validé manuellement ; le test de protocole vérifie que la requête de chat utilise le modèle choisi.
- `git ls-remote` n'a retourné aucune référence pour le dépôt cible ; authentification de publication à vérifier.
- Diff de l'ensemble des huit fichiers relu ; aucun fichier de cache, historique, réglage ou secret dans les fichiers suivis. `git diff --check` : réussi.

## 2026-10-01 — Publication

- Commit initial `0343235` créé et poussé sur `origin/main` avec le script de publication via Git Bash.
- `git ls-remote origin refs/heads/main` : hash distant identique au commit local `0343235`.
- Aucun déploiement applicatif distinct du dépôt GitHub n'a été effectué ou vérifié.
- Sélection manuelle du modèle dans la fenêtre et comportement des images selon chaque modèle restent à vérifier dans une session utilisateur complète.
