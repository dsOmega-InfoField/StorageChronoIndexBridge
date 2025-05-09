-- If you build NeoVim in an isolated environment, you might have different
-- Python that most likely won't have jupynium installed.
vim.g.python3_host_prog = { "pixi", "run", "python" }
