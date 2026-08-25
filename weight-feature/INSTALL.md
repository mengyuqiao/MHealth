# Weight Feature — Installation

## Files to copy to ~/hnc-tracker/

1. `database.py`           → ~/hnc-tracker/database.py
2. `weight_patch.py`       → ~/hnc-tracker/weight_patch.py
3. `weight_log.html`       → ~/hnc-tracker/templates/patient/weight_log.html
4. `weight_saved.html`     → ~/hnc-tracker/templates/patient/weight_saved.html
5. Append `weight_styles.css` content → ~/hnc-tracker/static/css/style.css

## Then run on server:

```bash
cd ~/hnc-tracker
conda activate hnc-tracker

# Append CSS
cat weight_styles.css >> static/css/style.css

# Patch app.py + home.html + clinician/patient.html
python weight_patch.py

# Restart app
tmux kill-session -t hnc
bash run.sh
```
