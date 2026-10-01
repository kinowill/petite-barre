# Document maître — Petite Barre

## État constaté le 1 octobre 2026

- Application de bureau Windows en Python/Tkinter, actuellement dans `app.py`.
- Dépendances déclarées dans `requirements.txt` : Pillow, tkinterdnd2 et mistune.
- Conversation Ollama via l'API HTTP locale `/api/chat` ; modèle codé en dur dans `app.py` au point de départ.
- Historique et réglages enregistrés localement dans le profil utilisateur Windows.
- Le dossier de travail initial ne contient pas de dépôt Git. L'état du dépôt GitHub cible reste à vérifier.
- Aucun déploiement n'était établi au point de départ.

## Objectif autorisé

Préparer le projet pour publication dans `kinowill/petite-barre` et permettre le choix de n'importe quel modèle Ollama installé. L'utilisateur a retiré la demande d'intégration d'une API externe.

## Comportements à préserver

- Barre Windows, saisie et réponses en flux, arrêt de génération, historique et contexte.
- Prompt système, mode réflexion, synthèse vocale et démarrage Windows.
- Ajout d'images, avec remontée de l'erreur Ollama si le modèle choisi ne les accepte pas.
- Aucun secret dans le code publié ou les journaux de validation.

## Résultat attendu pour le choix de modèle

- La barre liste les modèles installés via Ollama et laisse choisir celui utilisé pour les prochaines questions.
- Le choix est conservé localement entre les démarrages.
- Un changement de modèle efface le contexte de conversation en mémoire pour éviter de mêler les échanges de deux modèles ; l'historique enregistré reste consultable.
- Si Ollama est absent ou ne contient aucun modèle, l'interface donne une erreur compréhensible et ne lance aucune génération.

## Contrôles prévus

- Vérification du protocole HTTP et des erreurs avec tests ciblés.
- Vérification de syntaxe et analyse statique disponibles.
- Relecture du diff, contrôle des fichiers suivis et état Git avant publication.
- Essai réel de l'interface et de la liste Ollama ; génération réelle à consigner séparément si elle est effectuée.

## États de livraison

| État | Valeur |
| --- | --- |
| Dépôt modifié | Oui, code et documentation validés localement ; publication en attente |
| Production alignée | Non vérifiée |
| Validation réelle effectuée | Oui, ouverture de la barre, liste locale et génération avec `qwen3.5:2b` ; sélection manuelle dans la fenêtre non vérifiée |
