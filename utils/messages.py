DEFAULT_USER = "Sistema"

MESSAGES = {
    "zone": {
        "activated": "{user} ha attivato {zone} per {duration} minuti",
        "deactivated": "{user} ha disattivato {zone}",
        "auto_activated": "Ciclo automatico avviato: {zone} attiva per {duration} minuti",
        "auto_deactivated": "Ciclo automatico completato: {zone} disattivata",
        "manual_override": "Ciclo automatico in pausa: {user} ha attivato {zone} manualmente",
        "auto_resumed": "Ciclo automatico ripreso: {zone} attiva per {duration} minuti rimanenti",
        "timeout_deactivated": "{zone} disattivata automaticamente per timeout",
        "not_found": "Zona {zone} non trovata o non attiva",
        "error": "Errore nell'attivazione di {zone}",
    },
    "program_control": {
        "paused": "{user} ha messo in pausa '{name}' ({remaining} min rimanenti)",
        "resumed": "{user} ha ripreso '{name}' ({remaining} min rimanenti)",
        "stopped": "{user} ha fermato il programma '{name}'",
        "not_running": "Il programma non è in esecuzione",
        "not_paused": "Nessun programma in pausa con questo ID",
        "window_expired": "La finestra temporale del programma è scaduta: non è più possibile riprendere",
        "zone_busy": "Impossibile riprendere: un'altra zona è attiva",
        "no_time": "Nessun tempo disponibile prima del prossimo programma schedulato",
    },
    "program": {
        "created": "Programma '{name}' creato con successo",
        "edited": "Programma '{name}' modificato con successo",
        "deleted": "Programma eliminato con successo",
        "conflict": "Conflitto con il programma '{name}': orario già occupato",
        "not_found": "Programma non trovato",
        "error_create": "Errore nella creazione del programma",
        "error_edit": "Errore nella modifica del programma",
        "error_delete": "Errore nell'eliminazione del programma",
    },
}
