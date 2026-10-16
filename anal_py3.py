from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path
import random
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import requests

# ReportLab για εξαγωγή PDF
try:
  from reportlab.lib.pagesizes import A4
  from reportlab.pdfbase import pdfmetrics
  from reportlab.pdfbase.ttfonts import TTFont
  from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
  from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

  PDF_AVAILABLE = True
except ImportError:
  PDF_AVAILABLE = False

OPAP_GAME_IDS = {"joker": 5104, "lotto": 5103}


def weekly_daterange(start_date, end_date):
  current = start_date
  while current <= end_date:
    week_end = current + timedelta(days=6)
    if week_end > end_date:
      week_end = end_date
    yield current, week_end
    current = week_end + timedelta(days=1)


class LotteryCompleteGUI:

  def __init__(self, root):
    self.root = root
    self.root.title("Προηγμένη Ανάλυση Λόττο & Τζόκερ (ΟΠΑΠ)")
    self.root.geometry("1350x780")
    self.root.minsize(1050, 650)

    style = ttk.Style()
    style.theme_use("clam")

    top_frame = ttk.Frame(root, padding=10)
    top_frame.pack(fill=tk.X)

    ttk.Label(
        top_frame, text="Επιλογή Παιχνιδιού:", font=("Segoe UI", 11, "bold")
    ).pack(side=tk.LEFT, padx=5)

    self.game_var = tk.StringVar(value="joker")
    ttk.Radiobutton(
        top_frame, text="Τζόκερ", variable=self.game_var, value="joker"
    ).pack(side=tk.LEFT, padx=5)
    ttk.Radiobutton(
        top_frame, text="Λόττο", variable=self.game_var, value="lotto"
    ).pack(side=tk.LEFT, padx=5)

    # Εύρος Ανάλυσης
    ttk.Label(
        top_frame, text="Εύρος:", font=("Segoe UI", 10, "bold")
    ).pack(side=tk.LEFT, padx=(10, 2))
    self.range_var = tk.IntVar(value=10)
    range_combo = ttk.Combobox(
        top_frame,
        textvariable=self.range_var,
        values=[5, 10, 15, 20],
        state="readonly",
        width=4,
    )
    range_combo.pack(side=tk.LEFT, padx=2)
    range_combo.bind(
        "<<ComboboxSelected>>",
        lambda e: hasattr(self, "parsed_data") and self.refresh_ui_with_range(),
    )

    # Μετατόπιση (Offset)
    ttk.Label(
        top_frame, text="Μετατόπιση (Offset):", font=("Segoe UI", 10, "bold")
    ).pack(side=tk.LEFT, padx=(10, 2))
    self.offset_var = tk.IntVar(value=0)
    offset_spin = ttk.Spinbox(
        top_frame,
        from_=0,
        to=100,
        textvariable=self.offset_var,
        width=5,
        command=lambda: hasattr(self, "parsed_data")
        and self.refresh_ui_with_range(),
    )
    offset_spin.pack(side=tk.LEFT, padx=2)
    offset_spin.bind(
        "<Return>",
        lambda e: hasattr(self, "parsed_data") and self.refresh_ui_with_range(),
    )

    load_btn = ttk.Button(
        top_frame, text="Φόρτωση & Ανάλυση", command=self.run_analysis
    )
    load_btn.pack(side=tk.LEFT, padx=10)

    manual_btn = ttk.Button(
        top_frame,
        text="➕ Χειροκίνητη Προσθήκη",
        command=self.open_manual_add_dialog,
    )
    manual_btn.pack(side=tk.LEFT, padx=5)

    self.notebook = ttk.Notebook(root)
    self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    self.tab1 = ttk.Frame(self.notebook)
    self.notebook.add(
        self.tab1, text="1. Τελευταίες Κληρώσεις (Αναλυτικά)"
    )
    self.setup_tab1()

    self.tab2 = ttk.Frame(self.notebook)
    self.notebook.add(self.tab2, text="2. Συχνότητες & Καθυστερήσεις (Έτος)")
    self.setup_tab2()

    self.tab3 = ttk.Frame(self.notebook)
    self.notebook.add(self.tab3, text="3. Προτάσεις & Στατιστική Δικαίωση")
    self.setup_tab3()

  def setup_tab1(self):
    cols = ("draw_id", "date", "numbers", "categorization", "prev_appearance")
    self.tree1 = ttk.Treeview(self.tab1, columns=cols, show="headings", height=15)
    self.tree1.heading("draw_id", text="Draw ID")
    self.tree1.heading("date", text="Ημερομηνία")
    self.tree1.heading("numbers", text="Κληρωθέντες Αριθμοί")
    self.tree1.heading("categorization", text="Κατηγορίες (Εύρους προηγ.)")
    self.tree1.heading(
        "prev_appearance", text="Αμέσως Προηγούμενη Εμφάνιση ανά Αριθμό"
    )

    self.tree1.column("draw_id", width=80, anchor=tk.CENTER)
    self.tree1.column("date", width=95, anchor=tk.CENTER)
    self.tree1.column("numbers", width=170, anchor=tk.W)
    self.tree1.column("categorization", width=220, anchor=tk.W)
    self.tree1.column("prev_appearance", width=380, anchor=tk.W)

    scrollbar1 = ttk.Scrollbar(
        self.tab1, orient=tk.VERTICAL, command=self.tree1.yview
    )
    self.tree1.configure(yscroll=scrollbar1.set)
    self.tree1.pack(
        side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5
    )
    scrollbar1.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)

  def setup_tab2(self):
    cols = (
        "number",
        "total_freq",
        "total_delay",
        "yearly_freq_str",
        "yearly_delay_str",
    )
    self.tree2 = ttk.Treeview(self.tab2, columns=cols, show="headings", height=15)
    self.tree2.heading("number", text="Αριθμός")
    self.tree2.heading("total_freq", text="Συνολ. Εμφανίσεις")
    self.tree2.heading("total_delay", text="Συνολ. Καθυστέρηση")
    self.tree2.heading("yearly_freq_str", text="Εμφανίσεις ανά Έτος")
    self.tree2.heading("yearly_delay_str", text="Καθυστερήσεις ανά Έτος")

    self.tree2.column("number", width=80, anchor=tk.CENTER)
    self.tree2.column("total_freq", width=110, anchor=tk.CENTER)
    self.tree2.column("total_delay", width=120, anchor=tk.CENTER)
    self.tree2.column("yearly_freq_str", width=340, anchor=tk.W)
    self.tree2.column("yearly_delay_str", width=340, anchor=tk.W)

    scrollbar2 = ttk.Scrollbar(
        self.tab2, orient=tk.VERTICAL, command=self.tree2.yview
    )
    self.tree2.configure(yscroll=scrollbar2.set)
    self.tree2.pack(
        side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5
    )
    scrollbar2.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)

  def setup_tab3(self):
    ctrl_frame = ttk.Frame(self.tab3, padding=5)
    ctrl_frame.pack(fill=tk.X)

    ttk.Label(
        ctrl_frame,
        text="Ταξινόμηση Διαθέσιμων Αριθμών:",
        font=("Segoe UI", 9, "bold"),
    ).pack(side=tk.LEFT, padx=5)

    self.sort_mode_var = tk.StringVar(value="Συνολικές Εμφανίσεις (Αύξουσα)")
    sort_combo = ttk.Combobox(
        ctrl_frame,
        textvariable=self.sort_mode_var,
        values=[
            "Συνολικές Εμφανίσεις (Αύξουσα)",
            "Εμφανίσεις Έτους (Αύξουσα)",
        ],
        state="readonly",
        width=30,
    )
    sort_combo.pack(side=tk.LEFT, padx=5)
    sort_combo.current(0)
    sort_combo.bind(
        "<<ComboboxSelected>>",
        lambda e: hasattr(self, "parsed_data") and self.refresh_ui_with_range(),
    )

    open_win_btn = ttk.Button(
        ctrl_frame,
        text="🔍 Άνοιγμα Προτάσεων & Σύγκρισης σε Νέο Παράθυρο",
        command=self.open_suggestions_window,
    )
    open_win_btn.pack(side=tk.LEFT, padx=15)

    text_frame = ttk.Frame(self.tab3)
    text_frame.pack(fill=tk.BOTH, expand=True)

    self.text3 = tk.Text(
        text_frame,
        wrap=tk.WORD,
        font=("Consolas", 10),
        bg="#fdfdfd",
        padx=10,
        pady=10,
    )
    self.text3.tag_config(
        "available", foreground="#008000", font=("Consolas", 10, "bold")
    )
    self.text3.tag_config(
        "excluded", foreground="#CC0000", font=("Consolas", 10, "bold")
    )

    scrollbar3 = ttk.Scrollbar(
        text_frame, orient=tk.VERTICAL, command=self.text3.yview
    )
    self.text3.configure(yscroll=scrollbar3.set)
    self.text3.pack(
        side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5
    )
    scrollbar3.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)

  def open_suggestions_window(self):
    if not hasattr(self, "parsed_data") or not self.parsed_data:
      messagebox.showwarning(
          "Προειδοποίηση",
          "Δεν υπάρχουν διαθέσιμα δεδομένα ανάλυσης. Εκτελέστε πρώτα φόρτωση.",
      )
      return

    win = tk.Toplevel(self.root)
    win.title(
        "Αυτόματος Αλγόριθμος & Συνολική Αθροιστική Επιλογή (5, 10, 15, 20)"
    )
    win.geometry("1000x820")
    win.grab_set()

    btn_frame = ttk.Frame(win, padding=5)
    btn_frame.pack(fill=tk.X, padx=10, pady=5)

    save_txt_btn = ttk.Button(
        btn_frame,
        text="💾 Αποθήκευση σε TXT",
        command=self.export_report_txt,
    )
    save_txt_btn.pack(side=tk.LEFT, padx=5)

    save_pdf_btn = ttk.Button(
        btn_frame,
        text="📄 Αποθήκευση σε PDF",
        command=self.export_report_pdf,
    )
    save_pdf_btn.pack(side=tk.LEFT, padx=5)

    txt_frame = ttk.Frame(win)
    txt_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    txt = tk.Text(
        txt_frame,
        wrap=tk.WORD,
        font=("Consolas", 10),
        bg="#fdfdfd",
        padx=10,
        pady=10,
    )
    txt.tag_config(
        "available", foreground="#008000", font=("Consolas", 10, "bold")
    )
    txt.tag_config(
        "excluded", foreground="#CC0000", font=("Consolas", 10, "bold")
    )
    txt.tag_config(
        "optimal", foreground="#B8860B", font=("Consolas", 10, "bold")
    )
    txt.tag_config(
        "cumulative", foreground="#4B0082", font=("Consolas", 10, "bold")
    )  # Μωβ/Indigo
    txt.tag_config(
        "history", foreground="#000080", font=("Consolas", 10, "italic")
    )

    scrollbar = ttk.Scrollbar(txt_frame, orient=tk.VERTICAL, command=txt.yview)
    txt.configure(yscroll=scrollbar.set)
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    report_lines = self.generate_advanced_algorithmic_report()
    self.last_generated_report = report_lines

    for line in report_lines:
      if "Διαθέσιμοι:" in line or "Προτεινόμενος Αριθμός:" in line:
        txt.insert(tk.END, line + "\n", "available")
      elif "Αποκλεισμένοι:" in line:
        txt.insert(tk.END, line + "\n", "excluded")
      elif "⭐ [ΟΡΙΣΤΙΚΗ ΕΠΙΛΟΓΗ" in line or "Προτεινόμενο Πλήθος" in line:
        txt.insert(tk.END, line + "\n", "optimal")
      elif (
          "🌐 [Αθροιστικός Συνδυασμός" in line
          or "ΣΥΝΟΛΙΚΗ ΑΘΡΟΙΣΤΙΚΗ" in line
      ):
        txt.insert(tk.END, line + "\n", "cumulative")
      elif "💡 [Ιστορική Ανάλυση" in line:
        txt.insert(tk.END, line + "\n", "history")
      else:
        txt.insert(tk.END, line + "\n")

  def export_report_txt(self):
    if not hasattr(self, "last_generated_report"):
      return
    file_path = filedialog.asksaveasfilename(
        defaultextension=".txt",
        filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        title="Αποθήκευση Αναφοράς ως TXT",
    )
    if file_path:
      try:
        with open(file_path, "w", encoding="utf-8") as f:
          f.write("\n".join(self.last_generated_report))
        messagebox.showinfo(
            "Επιτυχία", "Η αναφορά αποθηκεύτηκε επιτυχώς σε TXT!"
        )
      except Exception as e:
        messagebox.showerror(
            "Σφάλμα", f"Αποτυχία αποθήκευσης αρχείου: {e}"
        )

  def export_report_pdf(self):
    if not PDF_AVAILABLE:
      messagebox.showerror(
          "Σφάλμα",
          "Η βιβλιοθήκη reportlab δεν είναι εγκατεστημένη. Δεν είναι δυνατή η"
          " δημιουργία PDF.",
      )
      return
    if not hasattr(self, "last_generated_report"):
      return

    file_path = filedialog.asksaveasfilename(
        defaultextension=".pdf",
        filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")],
        title="Αποθήκευση Αναφοράς ως PDF",
    )
    if file_path:
      try:
        doc = SimpleDocTemplate(
            file_path,
            pagesize=A4,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40,
        )
        font_name = "Helvetica"
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        if Path(font_path).exists():
          try:
            pdfmetrics.registerFont(TTFont("DejaVu", font_path))
            font_name = "DejaVu"
          except Exception:
            pass

        styles = getSampleStyleSheet()
        style_normal = ParagraphStyle(
            "ReportNormal",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=12,
        )
        style_title = ParagraphStyle(
            "ReportTitle",
            parent=styles["Heading1"],
            fontName=font_name,
            fontSize=11,
            leading=14,
            textColor="#000080",
        )

        story = []
        for line in self.last_generated_report:
          if not line.strip():
            story.append(Spacer(1, 4))
            continue
          if line.startswith("===") or line.startswith("---") or "⭐" in line:
            story.append(Paragraph(line, style_title))
          else:
            story.append(Paragraph(line, style_normal))

        doc.build(story)
        messagebox.showinfo(
            "Επιτυχία", "Η αναφορά αποθηκεύτηκε επιτυχώς σε PDF!"
        )
      except Exception as e:
        messagebox.showerror(
            "Σφάλμα", f"Αποτυχία δημιουργίας PDF: {e}"
        )

  def generate_advanced_algorithmic_report(self):
    parsed = self.parsed_data
    offset = self.offset_var.get()
    if offset >= len(parsed):
      offset = len(parsed) - 1
    analysis_parsed = parsed[offset:]

    game_type = self.game_var.get()
    max_num = 45 if game_type == "joker" else 49
    all_nums = list(range(1, max_num + 1))
    current_year = datetime.now().year

    flat_all = [num for draw in analysis_parsed for num in draw["numbers"]]
    overall_freq = Counter(flat_all)

    overall_delays = {}
    for num in all_nums:
      matching = [
          i for i, draw in enumerate(analysis_parsed) if num in draw["numbers"]
      ]
      overall_delays[num] = matching[0] if matching else len(analysis_parsed)

    years = sorted(list(set(d["year"] for d in analysis_parsed)), reverse=True)
    yearly_freq = {y: Counter() for y in years}
    for y in years:
      y_draws = [d for d in analysis_parsed if d["year"] == y]
      yearly_freq[y] = Counter([num for d in y_draws for num in d["numbers"]])

    blocked_delays = set()
    if len(analysis_parsed) >= 2:
      for n in set([n for d in analysis_parsed[:2] for n in d["numbers"]]):
        for j, draw in enumerate(analysis_parsed[1:], start=1):
          if n in draw["numbers"]:
            blocked_delays.add(j)
    if 1 in blocked_delays:
      blocked_delays.remove(1)

    sort_choice = self.sort_mode_var.get()
    is_yearly_sort = "Έτους" in sort_choice

    def get_sort_key(n):
      return (
          yearly_freq.get(current_year, {}).get(n, 0)
          if is_yearly_sort
          else overall_freq[n]
      )

    report_lines = []
    report_lines.append(
        "=== ΑΥΤΟΜΑΤΟΣ ΑΛΓΟΡΙΘΜΟΣ ΑΠΟΦΑΣΗΣ & ΣΥΓΚΡΙΣΗ ΕΥΡΟΥΣ (5, 10, 15, 20)"
        " ==="
    )
    report_lines.append(
        f"[Παράμετροι]: Παιχνίδι: {game_type.upper()} | Μετατόπιση (Offset):"
        f" {offset} κληρώσεις πίσω\n"
    )

    ranges_to_compare = [5, 10, 15, 20]
    parsed_chrono = sorted(analysis_parsed, key=lambda x: x["draw_id"])

    cumulative_all_picks = []
    range_picks_dict = {}

    for limit in ranges_to_compare:
      report_lines.append(f"--- ΑΝΑΛΥΣΗ ΓΙΑ ΕΥΡΟΣ {limit} ΚΛΗΡΩΣΕΩΝ ---")
      counts_n = Counter(
          [num for draw in analysis_parsed[:limit] for num in draw["numbers"]]
      )

      if limit >= 15:
        cats = {0: [], 1: [], 2: [], 3: [], 4: [], "5+": []}
      else:
        cats = {0: [], 1: [], 2: [], "3+": []}

      for num in all_nums:
        c = counts_n[num]
        if limit >= 15:
          key = c if c <= 4 else "5+"
        else:
          key = c if c <= 2 else "3+"
        cats[key].append(num)

      optimal_picks_summary = []

      for cat, num_list in cats.items():
        total_avail_now = len(num_list)
        if total_avail_now == 0:
          continue

        hit_distribution_exact = Counter()
        total_checked_exact = 0

        for i in range(limit, len(parsed_chrono)):
          historic_range = parsed_chrono[i - limit : i]
          historic_counts = Counter(
              [num for d in historic_range for num in d["numbers"]]
          )

          if limit >= 15:
            current_cat_numbers = {
                n
                for n in all_nums
                if (
                    (historic_counts[n] if historic_counts[n] <= 4 else "5+")
                    == cat
                )
            }
          else:
            current_cat_numbers = {
                n
                for n in all_nums
                if (
                    (historic_counts[n] if historic_counts[n] <= 2 else "3+")
                    == cat
                )
            }

          past_pool_size = len(current_cat_numbers)
          target_draw = parsed_chrono[i]
          hits = len(current_cat_numbers.intersection(target_draw["numbers"]))

          if past_pool_size == total_avail_now:
            hit_distribution_exact[hits] += 1
            total_checked_exact += 1

        recommended_count = 0
        max_freq = -1
        for h_cnt, f_cnt in hit_distribution_exact.items():
          if f_cnt > max_freq:
            max_freq = f_cnt
            recommended_count = h_cnt

        f_list = sorted(
            [
                n
                for n in num_list
                if overall_delays[n] not in blocked_delays
            ],
            key=get_sort_key,
        )
        selected_numbers = f_list[:recommended_count] if f_list else []

        optimal_picks_summary.append(
            (cat, total_avail_now, recommended_count, selected_numbers)
        )

        exact_dist_parts = [
            f"{h}αριθμ:{f}κλ({f/total_checked_exact*100:.1f}%)"
            for h, f in sorted(hit_distribution_exact.items())
        ]
        exact_summary = (
            ", ".join(exact_dist_parts) if exact_dist_parts else "N/A"
        )

        report_lines.append(
            f"  • Κατηγορία {cat} (Δεξαμενή: {total_avail_now} αριθμοί) |"
            f" Ιστορικό ίδιου πλήθους: [{exact_summary}]"
        )
        report_lines.append(
            f"    🤖 [Αλγόριθμος Απόφασης]: Προτεινόμενο πλήθος επιλογής ="
            f" **{recommended_count} αριθμοί**"
        )

      report_lines.append(
          f"\n  ⭐ [ΟΡΙΣΤΙΚΗ ΕΠΙΛΟΓΗ ΑΡΙΘΜΩΝ ΓΙΑ ΕΥΡΟΣ {limit}]:"
      )
      final_combination = []
      for cat, pool_sz, rec_cnt, sel_nums in optimal_picks_summary:
        sel_str = ", ".join(map(str, sel_nums)) if sel_nums else "Κανένας"
        report_lines.append(
            f"    - Κατηγορία {cat}: Επιλέγονται {rec_cnt} αριθμοί ->"
            f" [{sel_str}]"
        )
        final_combination.extend(sel_nums)

      range_picks_dict[limit] = final_combination
      cumulative_all_picks.extend(final_combination)

      report_lines.append(
          f"    🎯 Τελική Συνδυαστική Στήλη ({len(final_combination)}"
          f" αριθμοί): {sorted(final_combination)}\n"
      )

    # --- ΝΕΟ: ΣΥΝΟΛΙΚΗ ΑΘΡΟΙΣΤΙΚΗ ΕΠΙΛΟΓΗ (5, 10, 15, 20) ---
    report_lines.append(
        "=== ΣΥΝΟΛΙΚΗ ΑΘΡΟΙΣΤΙΚΗ ΕΠΙΛΟΓΗ (5, 10, 15, 20 ΚΛΗΡΩΣΕΙΣ) ==="
    )
    freq_across_ranges = Counter(cumulative_all_picks)
    sorted_cumulative = sorted(
        freq_across_ranges.keys(),
        key=lambda x: (-freq_across_ranges[x], x),
    )
    cumulative_str = ", ".join(map(str, sorted_cumulative))
    report_lines.append(
        f"🌐 [Αθροιστικός Συνδυασμός (Όλα τα Εύρη)]:"
        f" [{cumulative_str}]"
    )
    report_lines.append(
        "    (Συνολικοί μοναδικοί αριθμοί που προτάθηκαν στα 4 εύρη:"
        f" {len(sorted_cumulative)})"
    )
    for num in sorted_cumulative:
      ranges_found = [
          str(l) for l in ranges_to_compare if num in range_picks_dict[l]
      ]
      report_lines.append(
          f"    - Αριθμός {num}: Προτάθηκε σε {len(ranges_found)} εύρη"
          f" ({', '.join(ranges_found)})"
      )

    return report_lines

  def get_categories_dict(self):
    limit = self.range_var.get()
    if limit >= 15:
      return {0: [], 1: [], 2: [], 3: [], 4: [], "5+": []}
    else:
      return {0: [], 1: [], 2: [], "3+": []}

  def classify_count(self, c):
    limit = self.range_var.get()
    if limit >= 15:
      if c == 0:
        return 0
      elif c == 1:
        return 1
      elif c == 2:
        return 2
      elif c == 3:
        return 3
      elif c == 4:
        return 4
      else:
        return "5+"
    else:
      if c == 0:
        return 0
      elif c == 1:
        return 1
      elif c == 2:
        return 2
      else:
        return "3+"

  def download_full_history_with_progress(self, game_type):
    game_id = OPAP_GAME_IDS.get(game_type, 5104)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
        "Referer": "https://www.opap.gr/",
        "Origin": "https://www.opap.gr",
    }
    start_date = datetime(1997, 1, 1)
    end_date = datetime.now()
    intervals = list(weekly_daterange(start_date, end_date))
    total_steps = len(intervals)

    prog_win = tk.Toplevel(self.root)
    prog_win.title(f"Λήψη Ιστορικού {game_type.upper()}")
    prog_win.geometry("400x150")
    prog_win.grab_set()
    prog_win.protocol("WM_DELETE_WINDOW", lambda: None)

    ttk.Label(
        prog_win,
        text=f"Κατέβασμα πλήρους ιστορικού για {game_type.upper()}...\nΠαρακαλώ περιμένετε.",
        font=("Segoe UI", 10, "bold"),
        justify=tk.CENTER,
    ).pack(pady=15)
    progress = ttk.Progressbar(
        prog_win, orient="horizontal", length=350, mode="determinate"
    )
    progress.pack(pady=5)
    progress["maximum"] = total_steps
    status_label = ttk.Label(prog_win, text="0 / 0 εβδομάδες", font=("Segoe UI", 9))
    status_label.pack(pady=5)
    prog_win.update()

    all_draws_dict = {}
    for i, (from_dt, to_dt) in enumerate(intervals):
      fromDate = from_dt.strftime("%Y-%m-%d")
      toDate = to_dt.strftime("%Y-%m-%d")
      url = f"https://api.opap.gr/draws/v3.0/{game_id}/draw-date/{fromDate}/{toDate}"
      try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200:
          data = response.json()
          draws_list = (
              data
              if isinstance(data, list)
              else data.get("content", data.get("draws", []))
          )
          for d in draws_list:
            did = d.get("drawId") or d.get("drawNo")
            if did:
              all_draws_dict[did] = d
      except Exception:
        pass
      progress["value"] = i + 1
      status_label.config(text=f"Επεξεργασία εβδομάδας {i+1} από {total_steps}")
      prog_win.update()

    prog_win.destroy()
    final_draws = list(all_draws_dict.values())
    final_draws.sort(key=lambda x: x.get("drawId") or x.get("drawNo", 0))
    if final_draws:
      filename = f"{game_type}_draws.json"
      with open(filename, "w", encoding="utf-8") as f:
        json.dump(final_draws, f, ensure_ascii=False, indent=4)
      return final_draws
    return []

  def fetch_recent_draws_from_api(self, game_type, existing_data):
    game_id = OPAP_GAME_IDS.get(game_type, 5104)
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=15)
    fromDate = start_dt.strftime("%Y-%m-%d")
    toDate = end_dt.strftime("%Y-%m-%d")
    url = f"https://api.opap.gr/draws/v3.0/{game_id}/draw-date/{fromDate}/{toDate}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
        "Referer": "https://www.opap.gr/",
        "Origin": "https://www.opap.gr",
    }
    try:
      max_existing_id = (
          max(
              [d.get("drawId") or d.get("drawNo", 0) for d in existing_data]
          )
          if existing_data
          else 0
      )
      response = requests.get(url, headers=headers, timeout=15)
      if response.status_code != 200:
        return existing_data, 0
      data = response.json()
      draws_list = (
          data
          if isinstance(data, list)
          else data.get("content", data.get("draws", []))
      )
      new_draws = []
      existing_ids = {d.get("drawId") or d.get("drawNo") for d in existing_data}
      for d in draws_list:
        did = d.get("drawId") or d.get("drawNo")
        if did and did > max_existing_id and did not in existing_ids:
          new_draws.append(d)
      if new_draws:
        new_draws.sort(key=lambda x: x.get("drawId") or x.get("drawNo", 0))
        updated_data = new_draws + existing_data
        filename = f"{game_type}_draws.json"
        with open(filename, "w", encoding="utf-8") as f:
          json.dump(updated_data, f, ensure_ascii=False, indent=4)
        return updated_data, len(new_draws)
      return existing_data, 0
    except Exception:
      return existing_data, 0

  def open_manual_add_dialog(self):
    dialog = tk.Toplevel(self.root)
    dialog.title("Χειροκίνητη Προσθήκη Κλήρωσης")
    dialog.geometry("400x320")
    dialog.grab_set()
    game_type = self.game_var.get()
    max_n = 45 if game_type == "joker" else 49

    ttk.Label(
        dialog,
        text=f"Προσθήκη νέας κλήρωσης για {game_type.upper()}",
        font=("Segoe UI", 10, "bold"),
    ).pack(pady=10)
    ttk.Label(dialog, text="Draw ID (π.χ. 2541):").pack(anchor=tk.W, padx=20)
    id_entry = ttk.Entry(dialog, width=35)
    id_entry.pack(padx=20, pady=2)
    ttk.Label(dialog, text="Ημερομηνία (YYYY-MM-DD):").pack(
        anchor=tk.W, padx=20, pady=(5, 2)
    )
    date_entry = ttk.Entry(dialog, width=35)
    date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
    date_entry.pack(padx=20, pady=2)
    ttk.Label(
        dialog, text=f"Αριθμοί (χωρισμένοι με κόμμα, 1-{max_n}):"
    ).pack(anchor=tk.W, padx=20, pady=(5, 2))
    nums_entry = ttk.Entry(dialog, width=35)
    nums_entry.pack(padx=20, pady=2)

    def save_manual():
      try:
        did_val = int(id_entry.get().strip())
        dt_str = date_entry.get().strip()
        dt = datetime.strptime(dt_str, "%Y-%m-%d")
        raw_nums = [
            int(x.strip()) for x in nums_entry.get().split(",") if x.strip()
        ]
        if not raw_nums:
          raise ValueError("Δεν δόθηκαν αριθμοί.")
        new_entry = {
            "drawId": did_val,
            "drawTime": dt.isoformat() + "Z",
            "winningNumbers": {"list": raw_nums},
        }
        filename = f"{game_type}_draws.json"
        existing_data = []
        if Path(filename).exists():
          with open(filename, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
        if any(
            (d.get("drawId") == did_val or d.get("drawNo") == did_val)
            for d in existing_data
        ):
          messagebox.showerror(
              "Σφάλμα",
              "Αυτό το Draw ID υπάρχει ήδη στη βάση.",
              parent=dialog,
          )
          return
        existing_data.insert(0, new_entry)
        with open(filename, "w", encoding="utf-8") as f:
          json.dump(existing_data, f, ensure_ascii=False, indent=4)
        messagebox.showinfo(
            "Επιτυχία", "Η κλήρωση προστέθηκε επιτυχώς!", parent=dialog
        )
        dialog.destroy()
        self.run_analysis()
      except Exception as e:
        messagebox.showerror(
            "Σφάλμα", f"Μη έγκυρη καταχώρηση: {e}", parent=dialog
        )

    ttk.Button(
        dialog, text="Αποθήκευση & Εκτέλεση Ανάλυσης", command=save_manual
    ).pack(pady=20)

  def run_analysis(self):
    game_type = self.game_var.get()
    filename = f"{game_type}_draws.json"
    raw_data = []
    if Path(filename).exists():
      try:
        with open(filename, "r", encoding="utf-8") as f:
          raw_data = json.load(f)
      except Exception:
        raw_data = []
    if not raw_data:
      raw_data = self.download_full_history_with_progress(game_type)
    raw_data, new_count = self.fetch_recent_draws_from_api(game_type, raw_data)
    if not raw_data:
      messagebox.showerror("Σφάλμα", f"Το αρχείο {filename} παραμένει κενό.")
      return
    try:
      parsed = []
      for d in raw_data:
        did = d.get("drawId") or d.get("drawNo")
        draw_time = d.get("drawTime")
        dt = (
            datetime.fromtimestamp(draw_time / 1000.0)
            if isinstance(draw_time, int)
            else datetime.fromisoformat(str(draw_time).replace("Z", "+00:00"))
        )
        winning_numbers = d.get("winningNumbers", {})
        numbers = winning_numbers.get("list", []) or d.get("results", [])
        if numbers:
          parsed.append(
              {
                  "draw_id": did,
                  "date": dt,
                  "year": dt.year,
                  "numbers": sorted(numbers),
              }
          )
      parsed.sort(key=lambda x: x["draw_id"], reverse=True)
      self.parsed_data = parsed
      self.refresh_ui_with_range()
    except Exception as e:
      messagebox.showerror("Σφάλμα", f"Σφάλμα κατά την επεξεργασία: {e}")

  def refresh_ui_with_range(self):
    if not hasattr(self, "parsed_data") or not self.parsed_data:
      return
    parsed = self.parsed_data
    offset = self.offset_var.get()
    if offset >= len(parsed):
      offset = len(parsed) - 1
    analysis_parsed = parsed[offset:]

    game_type = self.game_var.get()
    max_num = 45 if game_type == "joker" else 49
    all_nums = list(range(1, max_num + 1))
    flat_all = [num for draw in analysis_parsed for num in draw["numbers"]]
    overall_freq = Counter(flat_all)
    overall_delays = {}
    for num in all_nums:
      matching = [
          i for i, draw in enumerate(analysis_parsed) if num in draw["numbers"]
      ]
      overall_delays[num] = matching[0] if matching else len(analysis_parsed)
    years = sorted(list(set(d["year"] for d in analysis_parsed)), reverse=True)
    yearly_freq = {y: Counter() for y in years}
    yearly_delays = {y: {} for y in years}
    for y in years:
      y_draws = [d for d in analysis_parsed if d["year"] == y]
      y_flat = [num for draw in y_draws for num in draw["numbers"]]
      yearly_freq[y] = Counter(y_flat)
      for num in all_nums:
        m_y = [
            i for i, draw in enumerate(y_draws) if num in draw["numbers"]
        ]
        yearly_delays[y][num] = m_y[0] if m_y else len(y_draws)
    self.populate_tab1(analysis_parsed)
    self.populate_tab2(
        all_nums, overall_freq, overall_delays, yearly_freq, yearly_delays, years
    )
    self.populate_tab3(
        analysis_parsed,
        all_nums,
        overall_freq,
        overall_delays,
        yearly_freq,
        yearly_delays,
        game_type,
    )

  def populate_tab1(self, analysis_parsed):
    for item in self.tree1.get_children():
      self.tree1.delete(item)
    limit = self.range_var.get()
    for i, draw in enumerate(analysis_parsed[:limit]):
      preceding_n = analysis_parsed[i + 1 : i + 1 + limit]
      flat_preceding = [num for d in preceding_n for num in d["numbers"]]
      counts_preceding = Counter(flat_preceding)
      cat_summary = self.get_categories_dict()
      for n in draw["numbers"]:
        c = counts_preceding[n]
        cat_summary[self.classify_count(c)].append(n)
      cat_str = " | ".join(
          [f"Κατηγ.{k}: {v}" for k, v in cat_summary.items() if v]
      )
      nums_str = ", ".join(map(str, draw["numbers"]))
      num_details = []
      for n in draw["numbers"]:
        prev_distance = None
        for j in range(i + 1, len(analysis_parsed)):
          if n in analysis_parsed[j]["numbers"]:
            prev_distance = j - i
            break
        if prev_distance is not None:
          num_details.append(f"Αρ.{n}:πριν {prev_distance}κλ.")
        else:
          num_details.append(f"Αρ.{n}:πρώτη")
      details_str = " | ".join(num_details)
      self.tree1.insert(
          "",
          tk.END,
          values=(
              draw["draw_id"],
              draw["date"].strftime("%Y-%m-%d"),
              nums_str,
              cat_str,
              details_str,
          ),
      )

  def populate_tab2(
      self,
      all_nums,
      overall_freq,
      overall_delays,
      yearly_freq,
      yearly_delays,
      years,
  ):
    for item in self.tree2.get_children():
      self.tree2.delete(item)
    for num in all_nums:
      tot_f, tot_d = overall_freq[num], overall_delays[num]
      y_f_str = ", ".join([f"{y}:{yearly_freq[y][num]}" for y in years[:5]])
      y_d_str = ", ".join([f"{y}:{yearly_delays[y][num]}" for y in years[:5]])
      self.tree2.insert("", tk.END, values=(num, tot_f, tot_d, y_f_str, y_d_str))

  def populate_tab3(
      self,
      analysis_parsed,
      all_nums,
      overall_freq,
      overall_delays,
      yearly_freq,
      yearly_delays,
      game_type,
  ):
    self.text3.delete("1.0", tk.END)
    limit = self.range_var.get()
    counts_n = Counter(
        [num for draw in analysis_parsed[:limit] for num in draw["numbers"]]
    )
    blocked_delays = set()
    if len(analysis_parsed) >= 2:
      for n in set([n for d in analysis_parsed[:2] for n in d["numbers"]]):
        for j, draw in enumerate(analysis_parsed[1:], start=1):
          if n in draw["numbers"]:
            blocked_delays.add(j)
    if 1 in blocked_delays:
      blocked_delays.remove(1)

    categories = self.get_categories_dict()
    for num in all_nums:
      categories[self.classify_count(counts_n[num])].append(num)

    current_year = datetime.now().year
    sort_choice = self.sort_mode_var.get()
    is_yearly_sort = "Έτους" in sort_choice

    def get_sort_key(n):
      return (
          yearly_freq.get(current_year, {}).get(n, 0)
          if is_yearly_sort
          else overall_freq[n]
      )

    report_lines = []
    report_lines.append(
        f"=== ΠΡΟΤΑΣΕΙΣ ΑΡΙΘΜΩΝ ΑΝΑ ΚΑΤΗΓΟΡΙΑ (Τελευταίες {limit} κληρώσεις)"
        " ==="
    )
    report_lines.append(
        "--- ΣΤΑΤΙΣΤΙΚΑ ΔΙΑΘΕΣΙΜΩΝ & ΑΠΟΚΛΕΙΣΜΕΝΩΝ ---\n"
    )

    for cat, num_list in categories.items():
      f_list = sorted(
          [
              n
              for n in num_list
              if overall_delays[n] not in blocked_delays
          ],
          key=get_sort_key,
      )
      e_list = sorted(
          [n for n in num_list if overall_delays[n] in blocked_delays],
          key=get_sort_key,
      )
      avail_str = ", ".join([str(n) for n in f_list]) if f_list else "Κανένας"
      excl_str = ", ".join([str(n) for n in e_list]) if e_list else "Κανένας"
      report_lines.append(
          f"• Κατηγορία {cat}: Διαθέσιμοι: [{avail_str}] | Αποκλεισμένοι:"
          f" [{excl_str}]"
      )

    report_lines.append("\n--- ΑΝΑΛΥΤΙΚΕΣ ΠΡΟΤΑΣΕΙΣ ---\n")
    for cat, num_list in categories.items():
      f_list = sorted(
          [
              n
              for n in num_list
              if overall_delays[n] not in blocked_delays
          ],
          key=get_sort_key,
      )
      if not f_list:
        continue

      report_lines.append(f"=== ΚΑΤΗΓΟΡΙΑ ΕΜΦΑΝΙΣΕΩΝ {cat} ===")
      for s_num in f_list:
        prev_dist_str = "πρώτη φορά"
        for j, draw in enumerate(analysis_parsed[1:], start=1):
          if s_num in draw["numbers"]:
            prev_dist_str = f"πριν {j} κληρώσεις"
            break
        report_lines.append(
            f"  * Διαθέσιμος Αριθμός: [{s_num}] (Εμφανίσεις στο διάστημα:"
            f" {counts_n[s_num]})"
        )
        report_lines.append(
            f"    [Στατιστικά]: Συνολ. Εμφανίσεις: {overall_freq[s_num]},"
            f" Καθυστέρηση: {overall_delays[s_num]} | Τελευταία εμφάνιση:"
            f" {prev_dist_str}"
        )
      report_lines.append("")

    for line in report_lines:
      if "Διαθέσιμοι:" in line or "Διαθέσιμος Αριθμός:" in line:
        self.text3.insert(tk.END, line + "\n", "available")
      elif "Αποκλεισμένοι:" in line:
        self.text3.insert(tk.END, line + "\n", "excluded")
      else:
        self.text3.insert(tk.END, line + "\n")


if __name__ == "__main__":
  root = tk.Tk()
  app = LotteryCompleteGUI(root)
  root.mainloop()