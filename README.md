# Modern Tetris

A minimalist, touch-friendly Tetris clone built with vanilla JavaScript, HTML and CSS. The game features the traditional 10x20 playfield, smooth animations, line clear scoring, and a modern neon-inspired interface.

## Features

- Classic 7-bag tetromino randomizer and 10x20 playfield
- Keyboard controls with support for hard drop, soft drop, rotation, and pausing
- Touch gestures for moving, rotating, and dropping pieces on mobile devices
- Dynamic score, level, and line tracking with progressively faster drop speeds
- Next piece preview and pause/game-over overlay

## Controls

| Action | Keyboard | Touch |
| ------ | -------- | ----- |
| Move left/right | Arrow Left / Arrow Right | Swipe left/right or tap ◀/▶ |
| Soft drop | Arrow Down | Swipe down or tap ▼ |
| Rotate | Arrow Up | Swipe up or tap ⟳ |
| Hard drop | Space | Tap ⤓ |
| Pause | P | Tap the pause button |

Use the Start button to begin a new game, Pause to pause/resume, and Reset to clear the board and scores.

## Getting started

Open `index.html` in a modern browser or serve the directory using a simple HTTP server:

```bash
python -m http.server 8000
```

Then visit <http://localhost:8000> to play.
