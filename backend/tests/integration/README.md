# Test di integrazione (database simulato)

Ogni `it_*.py` è uno script autonomo: carica `server.py` con un MongoDB finto in memoria e
modelli AI simulati, prova un flusso completo (liste, ricerca, task/to-do, azioni,
orologio, ...) e stampa `ALL OK` se tutte le verifiche passano. Non serve né un database
né una chiave API: girano in pochi secondi.

- Tutti: `python -m pytest -n 0 tests/test_integration_flows.py`
- Uno solo: `python tests/integration/it_lists.py`

`it_todo_search.py` usa il modello di embedding vero (fastembed): la prima volta lo scarica.
