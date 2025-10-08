const COLS = 10;
const ROWS = 20;
const BLOCK_SIZE = 24;

const KEY = {
  LEFT: "ArrowLeft",
  RIGHT: "ArrowRight",
  DOWN: "ArrowDown",
  ROTATE: "ArrowUp",
  DROP: "Space",
  HOLD: "KeyC",
  PAUSE: "KeyP"
};

const SHAPES = {
  I: [
    [0, 0, 0, 0],
    [1, 1, 1, 1],
    [0, 0, 0, 0],
    [0, 0, 0, 0]
  ],
  J: [
    [1, 0, 0],
    [1, 1, 1],
    [0, 0, 0]
  ],
  L: [
    [0, 0, 1],
    [1, 1, 1],
    [0, 0, 0]
  ],
  O: [
    [1, 1],
    [1, 1]
  ],
  S: [
    [0, 1, 1],
    [1, 1, 0],
    [0, 0, 0]
  ],
  T: [
    [0, 1, 0],
    [1, 1, 1],
    [0, 0, 0]
  ],
  Z: [
    [1, 1, 0],
    [0, 1, 1],
    [0, 0, 0]
  ]
};

const COLORS = {
  I: "#38bdf8",
  J: "#6366f1",
  L: "#f97316",
  O: "#facc15",
  S: "#22c55e",
  T: "#a855f7",
  Z: "#ef4444"
};

class Bag {
  constructor() {
    this.queue = [];
    this.fill();
  }

  fill() {
    const tetrominoes = Object.keys(SHAPES);
    while (tetrominoes.length) {
      const index = Math.floor(Math.random() * tetrominoes.length);
      const [piece] = tetrominoes.splice(index, 1);
      this.queue.push(piece);
    }
  }

  next() {
    if (this.queue.length === 0) {
      this.fill();
    }
    return this.queue.shift();
  }
}

class Piece {
  constructor(type) {
    this.type = type;
    this.matrix = SHAPES[type].map(row => [...row]);
    this.row = 0;
    this.col = Math.floor((COLS - this.matrix[0].length) / 2);
  }

  clone() {
    const copy = new Piece(this.type);
    copy.matrix = this.matrix.map(row => [...row]);
    copy.row = this.row;
    copy.col = this.col;
    return copy;
  }
}

class Board {
  constructor(rows, cols) {
    this.rows = rows;
    this.cols = cols;
    this.grid = this.createMatrix(rows, cols);
  }

  createMatrix(rows, cols) {
    return Array.from({ length: rows }, () => Array(cols).fill(null));
  }

  reset() {
    this.grid = this.createMatrix(this.rows, this.cols);
  }

  merge(piece) {
    piece.matrix.forEach((row, r) => {
      row.forEach((value, c) => {
        if (value) {
          const y = piece.row + r;
          const x = piece.col + c;
          if (y >= 0 && y < this.rows && x >= 0 && x < this.cols) {
            this.grid[y][x] = piece.type;
          }
        }
      });
    });
  }

  valid(piece) {
    return piece.matrix.every((row, r) =>
      row.every((value, c) => {
        if (!value) return true;
        const y = piece.row + r;
        const x = piece.col + c;
        return (
          y >= 0 && y < this.rows &&
          x >= 0 && x < this.cols &&
          !this.grid[y][x]
        );
      })
    );
  }

  sweep() {
    const rowsRemoved = [];
    for (let y = this.rows - 1; y >= 0; y--) {
      if (this.grid[y].every(cell => cell !== null)) {
        rowsRemoved.push(y);
      }
    }

    rowsRemoved.forEach(row => {
      this.grid.splice(row, 1);
      this.grid.unshift(Array(this.cols).fill(null));
    });

    return rowsRemoved.length;
  }
}

class Game {
  constructor() {
    this.canvas = document.getElementById("board");
    this.context = this.canvas.getContext("2d");
    this.context.scale(BLOCK_SIZE, BLOCK_SIZE);

    this.nextCanvas = document.getElementById("next");
    this.nextContext = this.nextCanvas.getContext("2d");
    this.nextScale = BLOCK_SIZE * 0.75;
    this.nextContext.scale(this.nextScale, this.nextScale);

    this.board = new Board(ROWS, COLS);
    this.bag = new Bag();
    this.nextPieceType = this.bag.next();
    this.currentPiece = null;

    this.dropCounter = 0;
    this.dropInterval = 1000;
    this.lastTime = 0;

    this.linesCleared = 0;
    this.score = 0;
    this.level = 1;

    this.running = false;
    this.paused = false;
    this.gameOver = false;

    this.overlay = document.getElementById("overlay");
    this.overlayTitle = document.getElementById("overlay-title");
    this.overlaySubtitle = document.getElementById("overlay-subtitle");

    this.$score = document.getElementById("score");
    this.$level = document.getElementById("level");
    this.$lines = document.getElementById("lines");

    this.startBtn = document.getElementById("start-btn");
    this.pauseBtn = document.getElementById("pause-btn");
    this.resetBtn = document.getElementById("reset-btn");
    this.resumeBtn = document.getElementById("resume-btn");
    this.touchPadButtons = Array.from(document.querySelectorAll(".touch-pad button"));

    this.bindUI();
    this.draw();
    this.drawNext();
  }

  bindUI() {
    document.addEventListener("keydown", event => {
      if (!this.running) return;
      if (event.repeat) return;

      switch (event.code) {
        case KEY.LEFT:
          event.preventDefault();
          this.move(-1);
          break;
        case KEY.RIGHT:
          event.preventDefault();
          this.move(1);
          break;
        case KEY.DOWN:
          event.preventDefault();
          this.softDrop();
          break;
        case KEY.ROTATE:
          event.preventDefault();
          this.rotate(1);
          break;
        case KEY.DROP:
          event.preventDefault();
          this.hardDrop();
          break;
        case KEY.PAUSE:
          event.preventDefault();
          this.togglePause();
          break;
        default:
          break;
      }
    });

    this.startBtn.addEventListener("click", () => this.start());
    this.pauseBtn.addEventListener("click", () => this.togglePause());
    this.resetBtn.addEventListener("click", () => this.reset());
    this.resumeBtn.addEventListener("click", () => this.togglePause(false));

    this.setupTouchControls();
    this.touchPadButtons.forEach(button => {
      button.addEventListener("click", event => {
        event.preventDefault();
        if (!this.running || this.paused) return;
        const action = button.dataset.action;
        this.handleButtonAction(action);
      });
    });
  }

  setupTouchControls() {
    let touchStartX = 0;
    let touchStartY = 0;
    let touchId = null;

    const threshold = 20;

    const onTouchStart = event => {
      if (!this.running || this.paused) return;
      const touch = event.changedTouches[0];
      touchId = touch.identifier;
      touchStartX = touch.clientX;
      touchStartY = touch.clientY;
    };

    const onTouchMove = event => {
      if (!this.running || this.paused || touchId === null) return;
      const touch = Array.from(event.changedTouches).find(t => t.identifier === touchId);
      if (!touch) return;

      const deltaX = touch.clientX - touchStartX;
      const deltaY = touch.clientY - touchStartY;

      if (Math.abs(deltaX) > Math.abs(deltaY)) {
        if (deltaX > threshold) {
          this.move(1);
          touchStartX = touch.clientX;
        } else if (deltaX < -threshold) {
          this.move(-1);
          touchStartX = touch.clientX;
        }
      } else {
        if (deltaY > threshold) {
          this.softDrop();
          touchStartY = touch.clientY;
        } else if (deltaY < -threshold) {
          this.rotate(1);
          touchStartY = touch.clientY;
        }
      }
    };

    const onTouchEnd = event => {
      const ended = Array.from(event.changedTouches).find(t => t.identifier === touchId);
      if (ended) {
        touchId = null;
      }
    };

    this.canvas.addEventListener("touchstart", onTouchStart, { passive: true });
    this.canvas.addEventListener("touchmove", onTouchMove, { passive: true });
    this.canvas.addEventListener("touchend", onTouchEnd);
  }

  start() {
    if (this.running) return;
    this.reset();
    this.running = true;
    this.spawnPiece();
    this.update();
  }

  reset() {
    this.board.reset();
    this.bag = new Bag();
    this.nextPieceType = this.bag.next();
    this.currentPiece = null;
    this.dropCounter = 0;
    this.dropInterval = 1000;
    this.lastTime = 0;
    this.linesCleared = 0;
    this.score = 0;
    this.level = 1;
    this.running = false;
    this.paused = false;
    this.gameOver = false;
    this.hideOverlay();
    this.updateStats();
    this.draw();
    this.drawNext();
  }

  spawnPiece() {
    const type = this.nextPieceType;
    this.currentPiece = new Piece(type);
    this.nextPieceType = this.bag.next();
    if (!this.board.valid(this.currentPiece)) {
      this.gameOver = true;
      this.running = false;
      this.showOverlay("Game Over", "Your final score: " + this.score.toLocaleString());
    }
    this.drawNext();
  }

  move(direction) {
    if (!this.currentPiece || this.paused) return;
    this.currentPiece.col += direction;
    if (!this.board.valid(this.currentPiece)) {
      this.currentPiece.col -= direction;
    }
    this.draw();
  }

  softDrop() {
    if (!this.currentPiece || this.paused) return;
    this.currentPiece.row++;
    if (!this.board.valid(this.currentPiece)) {
      this.currentPiece.row--;
      this.lockPiece();
      return;
    }
    this.score += 1;
    this.updateStats();
    this.draw();
  }

  hardDrop() {
    if (!this.currentPiece || this.paused) return;
    let dropDistance = 0;
    while (true) {
      this.currentPiece.row++;
      if (!this.board.valid(this.currentPiece)) {
        this.currentPiece.row--;
        break;
      }
      dropDistance++;
    }
    this.score += Math.max(0, dropDistance * 2);
    this.updateStats();
    this.lockPiece();
  }

  rotate(direction) {
    if (!this.currentPiece || this.paused) return;
    const cloned = this.currentPiece.clone();
    cloned.matrix = rotateMatrix(cloned.matrix, direction);

    const offsets = [0, -1, 1, -2, 2];
    for (const offset of offsets) {
      cloned.col = this.currentPiece.col + offset;
      if (this.board.valid(cloned)) {
        this.currentPiece.matrix = cloned.matrix;
        this.currentPiece.col = cloned.col;
        this.draw();
        return;
      }
    }
  }

  lockPiece() {
    this.board.merge(this.currentPiece);
    const cleared = this.board.sweep();
    if (cleared > 0) {
      this.handleLineClear(cleared);
    } else {
      this.updateStats();
    }
    this.dropCounter = 0;
    this.spawnPiece();
    this.draw();
  }

  handleButtonAction(action) {
    switch (action) {
      case "left":
        this.move(-1);
        break;
      case "right":
        this.move(1);
        break;
      case "down":
        this.softDrop();
        break;
      case "rotate":
        this.rotate(1);
        break;
      case "drop":
        this.hardDrop();
        break;
      default:
        break;
    }
  }

  handleLineClear(lines) {
    const lineScores = { 1: 100, 2: 300, 3: 500, 4: 800 };
    this.score += lineScores[lines] * this.level;
    this.linesCleared += lines;
    this.level = Math.floor(this.linesCleared / 10) + 1;
    this.dropInterval = Math.max(100, 1000 - (this.level - 1) * 75);
    this.updateStats();
  }

  updateStats() {
    this.$score.textContent = this.score.toLocaleString();
    this.$level.textContent = this.level;
    this.$lines.textContent = this.linesCleared;
  }

  update(time = 0) {
    if (!this.running) return;
    const delta = time - this.lastTime;
    this.lastTime = time;

    if (!this.paused) {
      this.dropCounter += delta;
      if (this.dropCounter > this.dropInterval) {
        this.drop();
      }
    }

    this.draw();
    requestAnimationFrame(t => this.update(t));
  }

  drop() {
    if (!this.currentPiece) return;
    this.currentPiece.row++;
    if (!this.board.valid(this.currentPiece)) {
      this.currentPiece.row--;
      this.lockPiece();
      this.dropCounter = 0;
      return;
    }
    this.dropCounter = 0;
  }

  draw() {
    this.context.clearRect(0, 0, this.canvas.width, this.canvas.height);
    drawMatrix(this.context, this.board.grid, { x: 0, y: 0 });
    if (this.currentPiece) {
      drawMatrix(this.context, this.currentPiece.matrix, { x: this.currentPiece.col, y: this.currentPiece.row }, this.currentPiece.type);
    }
  }

  drawNext() {
    this.nextContext.save();
    this.nextContext.setTransform(1, 0, 0, 1, 0, 0);
    this.nextContext.clearRect(0, 0, this.nextCanvas.width, this.nextCanvas.height);
    this.nextContext.restore();

    const type = this.nextPieceType;
    const matrix = SHAPES[type];

    const offsetX = Math.floor((4 - matrix[0].length) / 2);
    const offsetY = Math.floor((4 - matrix.length) / 2);

    drawMatrix(this.nextContext, matrix, { x: offsetX, y: offsetY }, type);
  }

  togglePause(force) {
    if (!this.running) return;
    if (typeof force === "boolean") {
      this.paused = force;
    } else {
      this.paused = !this.paused;
    }

    if (this.paused) {
      this.showOverlay("Paused", "Press resume or hit P to continue.");
    } else {
      this.hideOverlay();
    }
  }

  showOverlay(title, subtitle = "") {
    this.overlayTitle.textContent = title;
    this.overlaySubtitle.textContent = subtitle;
    this.overlay.hidden = false;
  }

  hideOverlay() {
    this.overlay.hidden = true;
  }
}

function rotateMatrix(matrix, direction = 1) {
  const size = matrix.length;
  const result = matrix.map(row => row.slice());
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (matrix[y] && matrix[y][x]) {
        if (direction > 0) {
          result[x][size - 1 - y] = matrix[y][x];
        } else {
          result[size - 1 - x][y] = matrix[y][x];
        }
      } else {
        if (direction > 0) {
          result[x][size - 1 - y] = 0;
        } else {
          result[size - 1 - x][y] = 0;
        }
      }
    }
  }
  return result;
}

function drawMatrix(context, matrix, offset, type) {
  context.save();
  context.translate(offset.x, offset.y);
  matrix.forEach((row, y) => {
    row.forEach((value, x) => {
      if (!value) return;
      context.fillStyle = COLORS[type] || COLORS[value] || "#94a3b8";
      context.fillRect(x, y, 1, 1);
      context.strokeStyle = "rgba(15, 23, 42, 0.65)";
      context.lineWidth = 0.05;
      context.strokeRect(x, y, 1, 1);
    });
  });
  context.restore();
}

window.addEventListener("DOMContentLoaded", () => {
  new Game();
});
