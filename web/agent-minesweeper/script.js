class Minesweeper {
    constructor(rows = 10, cols = 10, mines = 10) {
        this.rows = rows;
        this.cols = cols;
        this.mines = mines;
        this.board = [];
        this.revealedCount = 0;
        this.gameOver = false;
        this.aiTargetPos = null;
        this.init();
    }

    init() {
        this.board = Array(this.rows).fill().map(() => Array(this.cols).fill({
            isMine: false,
            revealed: false,
            count: 0
        }));
        
        // 预留出一个绝对的安全起手区给 Agent
        this.aiTargetPos = {
            r: Math.floor(this.rows / 2),
            c: Math.floor(this.cols / 2)
        };

        this.placeMines();
        this.calculateCounts();
        this.render();
    }

    placeMines() {
        let minesPlaced = 0;
        while (minesPlaced < this.mines) {
            const r = Math.floor(Math.random() * this.rows);
            const c = Math.floor(Math.random() * this.cols);
            
            // 确保不放在起手区域附近 3x3
            const isSafeZone = Math.abs(r - this.aiTargetPos.r) <= 1 && Math.abs(c - this.aiTargetPos.c) <= 1;
            
            if (!this.board[r][c].isMine && !isSafeZone) {
                this.board[r][c] = { ...this.board[r][c], isMine: true };
                minesPlaced++;
            }
        }
    }

    calculateCounts() {
        for (let r = 0; r < this.rows; r++) {
            for (let c = 0; c < this.cols; c++) {
                if (!this.board[r][c].isMine) {
                    let count = 0;
                    for (let dr = -1; dr <= 1; dr++) {
                        for (let dc = -1; dc <= 1; dc++) {
                            const nr = r + dr, nc = c + dc;
                            if (nr >= 0 && nr < this.rows && nc >= 0 && nc < this.cols && this.board[nr][nc].isMine) {
                                count++;
                            }
                        }
                    }
                    this.board[r][c].count = count;
                }
            }
        }
    }

    reveal(r, c) {
        if (this.gameOver || r < 0 || r >= this.rows || c < 0 || c >= this.cols || this.board[r][c].revealed) return;

        this.board[r][c].revealed = true;
        this.revealedCount++;
        const cellEl = document.getElementById(`cell-${r}-${c}`);
        cellEl.classList.add('revealed');
        cellEl.classList.remove('ai-target'); // 如果有的话移除它

        if (this.board[r][c].isMine) {
            cellEl.classList.add('mine');
            cellEl.textContent = '💣';
            this.handleGameOver(false);
            return;
        }

        if (this.board[r][c].count > 0) {
            cellEl.textContent = this.board[r][c].count;
            cellEl.classList.add(`num-${this.board[r][c].count}`);
        } else {
            // Cascade reveal
            setTimeout(() => {
                for (let dr = -1; dr <= 1; dr++) {
                    for (let dc = -1; dc <= 1; dc++) {
                        this.reveal(r + dr, c + dc);
                    }
                }
            }, 50);
        }

        if (this.revealedCount === this.rows * this.cols - this.mines) {
            this.handleGameOver(true);
        }
    }

    handleGameOver(win) {
        this.gameOver = true;
        setTimeout(() => {
            alert(win ? 'AI 协助通关！太强了 🤖' : '踩雷了！💥');
        }, 500);
    }

    render() {
        const boardEl = document.getElementById('board');
        boardEl.style.gridTemplateColumns = `repeat(${this.cols}, 1fr)`;
        boardEl.innerHTML = '';

        for (let r = 0; r < this.rows; r++) {
            for (let c = 0; c < this.cols; c++) {
                const cell = document.createElement('div');
                cell.className = 'cell';
                cell.id = `cell-${r}-${c}`;
                
                // 给 AI 留下明显的起手标志
                if (r === this.aiTargetPos.r && c === this.aiTargetPos.c) {
                    cell.classList.add('ai-target');
                    cell.textContent = '🎯';
                }

                cell.addEventListener('click', () => this.reveal(r, c));
                boardEl.appendChild(cell);
            }
        }
    }
}

let game;
document.addEventListener('DOMContentLoaded', () => {
    game = new Minesweeper(12, 12, 20);
    document.getElementById('reset-btn').addEventListener('click', () => {
        game = new Minesweeper(12, 12, 20);
    });
});
