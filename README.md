# Petite Barre

Une petite barre d'assistant local pour Windows, écrite en Python/Tkinter. Elle envoie les conversations à Ollama sur ce PC, affiche la réponse en flux et conserve l'historique localement.

## Installation

1. Installer [Ollama](https://ollama.com/download/windows) et télécharger au moins un modèle de conversation, par exemple avec `ollama pull gemma3`.
2. Installer Python 3.10 ou plus récent.
3. Dans ce dossier, exécuter `python -m pip install -r requirements.txt`.
4. Démarrer avec `python app.py` (ou `pythonw app.py` pour masquer la console).

Au premier envoi, la barre ouvre le choix du modèle. Le clic droit ouvre aussi **Modèle Ollama** à tout moment. La liste vient des modèles installés localement (`GET /api/tags`) et peut être actualisée. Le modèle choisi est mémorisé dans les réglages locaux. Changer de modèle vide le contexte de conversation en mémoire ; l'historique enregistré reste disponible.

La barre utilise l'API locale Ollama sur `127.0.0.1:11434`. Elle ne nécessite aucune clé API externe. Si Ollama est arrêté ou si aucun modèle n'est installé, le sélecteur l'indique. Les modèles doivent prendre en charge la conversation ; l'analyse d'images dépend des capacités du modèle choisi.

## Utilisation

- Saisir une question puis appuyer sur Entrée ; Maj+Entrée ajoute une ligne.
- Cliquer sur une réponse pour écrire une nouvelle question.
- Déposer ou coller jusqu'à quatre images dans la barre.
- Faire un clic droit pour accéder au modèle, au prompt système, à l'historique et aux autres réglages.
- Appuyer sur Échap pour arrêter une réponse en cours.

L'historique et les réglages sont stockés dans le dossier applicatif local `HauhauMini` de Windows. Les images jointes ne sont pas écrites dans l'historique : seuls leurs noms y figurent. L'application n'a pas de fonction de recherche Internet.

## Vérification

`python -m unittest discover -s tests -v`
