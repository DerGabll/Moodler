# 🧠 Moodler (Mein Schatz)

## 📘 Was ist der Moodler?

Der **Moodler** nimmt automatisch deinen letzten Screenshot aus dem **„Bildschirmfotos“**-Ordner und leitet das Bild an **GPT-5** weiter.  
ChatGPT liest den Text aus dem Screenshot aus und gibt dir **kurz die richtigen Antworten** aus (zu 99 %).

---

## ⚙️ Setup

1. Besorge dir einen [OpenAI API-Key](https://platform.openai.com/api-keys).  
2. Erstelle eine neue Datei namens **`.env`** im Projektordner und füge Folgendes ein:
   ```env
   OPENAI_API_KEY=dein_api_key
   ```
3. Öffne ein Terminal im Projektverzeichnis und installiere alle Abhängigkeiten:
   ```bash
   pip install -r requirements.txt
   ```
4. Starte anschließend das Programm:
   ```bash
   python main.py
   ```

---

## 🖥️ Verwendung

Nach dem Start erscheint oben links ein grüner Text:

> **"Waiting to read screenshot. Press ALT + R to load."**

### 📸 Schritt-für-Schritt:

1. Mache einen Screenshot einer **Multiple-Choice-Frage**.  
2. Drücke **Alt + R** – der letzte Screenshot wird zu GPT-5 weitergeleitet.  
3. Drücke **Alt + Enter**, um das Bild an ChatGPT zu senden.  
4. Nach kurzer Zeit erscheint die *richtige Lösung*.  
5. Drücke erneut **Alt + Enter**, um fortzufahren.

---

## ⚠️ Hinweis zu Moodle-Tests

> ❌ **Der Moodler ist **nicht** für Schulprüfungen, Tests oder benotete Moodle-Quizzes gedacht!**

Die Nutzung in solchen Kontexten kann als **Täuschungsversuch** gelten und **schulische Konsequenzen** haben  
(z. B. Punktabzug, Note 5 oder Disziplinarmaßnahmen).

✅ Verwende den Moodler **nur zu Lern-, Übungs- oder Forschungszwecken**, z. B.:
- Zum Testen eigener Quizze  
- Zum besseren Verständnis des Moodle-Systems

---

## ⚡ Haftungsausschluss

💡 Die Nutzung erfolgt **auf eigene Gefahr**.  
\*Die angezeigten Lösungen werden **automatisch generiert** und können **Fehler enthalten**.  
Bitte überprüfe die Ergebnisse **eigenständig**.

---
