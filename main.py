from __future__ import annotations

from app.ui import CSS, demo
from config import PORT

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=PORT,
        css=CSS,
    )
