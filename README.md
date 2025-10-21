# Moodler (Mein Schatz)

## Was ist der Moodler?

Der Moodler nimmt automatisch deinen letzten Screenshot im "Bildschirmfotos" Ordner und leitet das bild an gpt-5 weiter. Dann ließt ChatGPT den Text aus dem Bild und gibt dir kurz die richtigen Antworten aus (zu 99%).

## Setup

Zuerst muss man einen [API Key](https://platform.openai.com/api-keys) von Openai besorgen, danach eine neue .env Datei erstellen und folgendes einfügen: OPENAI_API_KEY=dein_api_key. Starte jetzt ein neues Terminal und begib dich in den Pfad, in der sich der Moodler befindet. Schreibe dann 
```pip install -r requirements.txt``` um alle gebrauchten Module zu installieren. Führe dann die main.py datei aus, um den Moodler zu starten.

## Verwendung

Zu Beginn sollte ein grüner Text auf der oberen linken Seite des Bildschirms mit den Worten "Waiting to read screenshot. Press ALT + R to load." erscheinen. Machen sie jetzt einen Screenshot von einer multiple-choice Frage und drücke alt + r. Der letzte Screenshot wird angezeigt und sie können mit alt + enter fortfahren. Danach wird ChatGPT das Bild verarbeiten und es wird ihnen nach kurzer Zeit die *richtige Lösung angezeigt. Drücken sie ein weiteres mal alt + enter und sie sind wieder am Start.

### Kann ich den Moodler für Schultests auf Moodle benutzen?

Der Moodler ist nicht dafür gedacht, bei Schulprüfungen, Tests oder benoteten Moodle-Quizzes verwendet zu werden.
Die Verwendung eines Quizlösers in solchen Kontexten kann als Täuschungsversuch oder Verstoß gegen Schul- bzw. Prüfungsordnungen gewertet werden.
Das kann schulische Konsequenzen haben – bis hin zu Punktabzug, Note 6 oder Disziplinarmaßnahmen.

Bitte verwende den Moodler nur zu Lern-, Übungs- oder Forschungszwecken – etwa, um eigene Quizze zu testen oder das Funktionsverhalten von Moodle besser zu verstehen.

💡 Hinweis: Die Nutzung erfolgt auf eigene Gefahr.
*Die angezeigte Lösung wird von ChatGPT automatisch generiert und kann Fehler enthalten. Sie gilt daher nicht immer als garantiert richtig – bitte überprüfen Sie die Ergebnisse eigenständig.
