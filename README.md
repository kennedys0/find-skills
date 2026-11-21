# find-skills

Skill finder untuk Kiro (dan agent lain yang pakai format Agent Skills / `SKILL.md`). Saat ini fokus ke **website dan web app**. Profil lain (game, dll.) menyusul.

Saat kamu mulai project, agent akan:

1. Cek apakah skill **anti-slop** (UI, kode, tulisan) sudah ada. Kalau belum, ini selalu ditawarkan paling atas.
2. Cari skill yang sudah terpasang di lokal (`.kiro/skills`, `~/.kiro/skills`, `.claude/skills`, `~/.agents/skills`, dll).
3. Kalau masih kurang, cari di katalog kurasi lalu di skills.sh dan GitHub, diurutkan berdasarkan stars, jumlah install, lisensi, dan seberapa aktif repo-nya.
4. Download kandidat ke folder staging, scan semua filenya, lalu agent membaca isinya sendiri.
5. Tanya kamu dulu, misalnya: *"Bolehkah saya install skill ini untuk anti-slop?"*
6. Install hanya yang kamu setujui, dikunci ke commit yang sudah dicek.

## Install

```bash
npx find-skills --website --auto     # global + trigger otomatis tiap project baru (disarankan)
npx find-skills --website            # global saja
npx find-skills --website --workspace          # hanya project di folder ini
npx find-skills --website --agent kiro --agent claude   # Kiro + Claude Code
npx find-skills list                 # lihat profil yang tersedia
npx find-skills uninstall            # hapus lagi
```

Pakai `npx`, bukan `npm install`: `npm install` tidak meneruskan flag seperti `--website` ke paketnya.

Langsung dari GitHub (tanpa registry npm):

```bash
npx github:kennedys0/find-skills --website --auto
npx github:kennedys0/find-skills#v1.1.0 --website    # kunci ke versi tertentu
npm install -g github:kennedys0/find-skills && find-skills --website
```

Atau tanpa npm: di Kiro IDE buka **Agent Steering & Skills → + → Import skill from a repository URL**, lalu tempel `https://github.com/kennedys0/find-skills/tree/main/skills/find-skills`. Cara ini menyalin semua profil dan tidak memasang steering `--auto`.

| Opsi | Arti |
|---|---|
| `--website` | profil website (ui-ux, frontend, performance-a11y, backend, security, testing, seo-marketing, deploy, workflow) |
| `--game` | *coming soon*, belum bisa di-install |
| `--all` | semua profil yang sudah stabil |
| `--workspace [dir]` | install ke `<dir>/.kiro/skills` saja; tanpa ini install global ke `~/.kiro/skills` |
| `--agent kiro\|claude\|agents` | target agent, boleh lebih dari satu (default `kiro`) |
| `--only` | ganti profil yang terpasang; default-nya profil baru **ditambahkan** ke yang lama |
| `--auto` | pasang steering `find-skills-auto.md` (mode `always`) supaya selalu terpicu di project baru |
| `--dry-run` | tampilkan rencana tanpa mengubah apa pun |

Menjalankan ulang `npx find-skills` tanpa profil akan meng-update skill dengan profil yang sama. Versi lama dipindah ke `skills-backup/`.

Tanpa `--auto`, skill tetap aktif kalau permintaanmu cocok dengan deskripsinya ("bikin website", "landing page", "cari skill untuk auth"), atau bisa dipanggil manual dengan `/find-skills`.

**Kebutuhan:** Node 18+ (untuk installer), Python 3.9+ (untuk helper yang dipakai agent), dan koneksi internet. Login `gh auth login` atau set `GITHUB_TOKEN` supaya tidak kena limit 60 request/jam dari GitHub.

## Anti-slop (wajib ditawarkan)

| Jenis | Rekomendasi utama | Alternatif |
|---|---|---|
| UI | `miqdadbadjuber/anti-slop` → `antislop`, `antislop-ui`, `antislop-layoutmobile` | `leonxlnx/taste-skill` → `design-taste-frontend` |
| Kode | `cursor/plugins` → `deslop` | `antislop-code` |
| Tulisan | `blader/humanizer` → `humanizer` | `hardikpandya/stop-slop`, `antislop-copywriting` |

Semua sudah lolos `vet` per 2026-11-21. `taste-skill` dapat REVIEW karena besar (sekitar 37 MB) dan menjalankan headless Chrome secara lokal.

## Pakai helper secara manual

```bash
SF="python3 ~/.kiro/skills/find-skills/scripts/skillfinder.py"
$SF baseline
$SF local nextjs
$SF catalog security
$SF search "supabase auth"
$SF vet vercel-labs/agent-skills vercel-react-best-practices
$SF install vercel-labs/agent-skills vercel-react-best-practices --sha <sha dari vet>
```

## Cara menilai kualitas dan keamanan

- **Skor kualitas (0–100):** stars, jumlah install, push terakhir, lisensi, pemilik terpercaya (vendor resmi). Dikurangi untuk fork, repo arsip, dan pola clone.
- **Deteksi clone:** banyak repo clone ber-star belasan tapi "install"-nya puluhan ribu (contoh: `101-skills/superpowers`, 31 stars, 67 ribu install). Ini otomatis REJECT.
- **Scan statis:** `curl | sh`, akses `~/.ssh` / kredensial, kirim token lewat network, prompt injection, Unicode tersembunyi, binary, `rm -rf /`, exec dinamis, network di script.
- **Verdict:** `PASS`, `REVIEW` (perlu dibaca dan disetujui), `REJECT` (tidak di-install kecuali kamu memaksa dengan `--force`).
- Scan itu pencocokan pola, jadi agent tetap wajib membaca SKILL.md dan semua script sebelum merekomendasikan.

## Menambah profil baru (untuk update berikutnya)

1. Buat `skills/find-skills/references/catalog/<nama>.json` dengan format yang sama seperti `website.json`: `profile`, `title`, `status`, `baseline_kinds`, `detect`, `domains`.
2. Selama belum siap, isi `"status": "draft"`. Installer akan menolaknya ("coming soon"), dan helper mengabaikannya kecuali `FIND_SKILLS_DRAFTS=1`.
3. Pastikan semua skill di katalog benar-benar ada di repo-nya dan lolos `vet`, lalu ubah ke `"status": "stable"` dan naikkan versi di `package.json`.

Flag `--<nama>` otomatis muncul dari nama file, jadi `bin/cli.js` tidak perlu diubah. `game.json` sudah ada sebagai draft.

## Struktur

```
bin/cli.js                    installer npx (tanpa dependency)
skills/find-skills/
├── SKILL.md                  alur kerja untuk agent
├── scripts/skillfinder.py    helper (stdlib saja)
└── references/
    ├── catalog/
    │   ├── core.json         baseline anti-slop, owner terpercaya, deteksi clone
    │   ├── website.json      profil website (stable)
    │   └── game.json         profil game (draft)
    └── vetting.md            checklist review manual
steering/find-skills-auto.md  trigger otomatis (opsional)
```

## Publish ke npm

Nama `find-skills` masih kosong di npm per 2026-11-21.

```bash
npm login
npm publish --dry-run   # cek isi paket dulu
npm publish
```
