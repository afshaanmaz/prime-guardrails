# On the VM, after setup-prime-lab.sh finishes

```bash
gcloud compute ssh prime-lab --zone us-central1-a

# install Claude Code and open a fresh shell so it's on PATH
curl -fsSL https://claude.ai/install.sh | bash
exec bash -l

# get your fork of the PRIME repo (experiments are on the local-eval branch) (gh asks you to enter a code on github.com; skip if the repo is public)
gh auth login
mkdir -p ~/work && cd ~/work
gh repo clone afshaanmaz/prime-guardrails && cd prime-guardrails
git checkout local-eval

# sign Claude Code in once with /login, then /exit
claude

# start Remote Control inside tmux so it survives your SSH disconnecting
tmux new -s claude
claude remote-control --name "PRIME lab"
# answer y to trust the folder and enable Remote Control, then press Ctrl-b then d to detach

# bring Remote Control back automatically whenever the VM starts
(crontab -l 2>/dev/null; echo "@reboot cd $PWD && /usr/bin/tmux new -d -s claude '$HOME/.local/bin/claude remote-control --name PRIME-lab'") | crontab -
```

Then open the Claude app on your phone, go to Code, and pick the PRIME lab session.

Guards on spend:
- Budget alert email at 50%, 90%, 100% of the weekend budget (alert only).
- VM stops itself 8 hours after each start.
- VM stops itself after 60 minutes with the GPU and CPU idle.
- To start it again from your phone: Compute Engine > VM instances > prime-lab > Start, in the Google Cloud console.
