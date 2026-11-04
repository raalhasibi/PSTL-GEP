# GENORA

**GEN**eration **O**ptimization and **R**esource **A**dequacy

Aplikasi Python berbahasa Indonesia untuk pembelajaran perencanaan kapasitas satu node.

Logo UMY Electrical Engineering di atas judul dimuat dari
`assets/umy_electrical_engineering.png`. Sertakan folder **assets** saat
menyalin proyek atau mengunggahnya ke GitHub/Streamlit Cloud.

## Menjalankan

Jika dependensi sudah terpasang, klik dua kali **Jalankan Aplikasi.cmd**.
Biarkan jendela peluncur terbuka selama menggunakan aplikasi. Menutup jendela
atau mematikan komputer akan menghentikan server; jalankan peluncur kembali
untuk sesi berikutnya. Alamat `http://127.0.0.1:8501` hanya dapat digunakan
di komputer yang menjalankan aplikasi. Jika aplikasi sudah berjalan, cukup
buka alamat tersebut tanpa menjalankan peluncur lagi.

Python 3.12 direkomendasikan. Dari folder proyek:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run app.py
```

Buka alamat lokal yang ditampilkan Streamlit (biasanya http://localhost:8501).

## Input dari Excel

Buka **Input dari Excel — unduh template dan unggah data** di bagian atas halaman.

1. Klik **Unduh Template Excel**.
2. Isi workbook dan simpan sebagai `.xlsx`. Baca sheet **Petunjuk** dan
   pertahankan nama sheet/header. Nilai contoh merupakan ilustrasi.
3. Pilih skenario eksperimen tujuan, unggah file pada **Unggah Excel (.xlsx)**,
   kemudian klik **Periksa Excel**.
4. Jika ada kesalahan, perbaiki sheet/baris/kolom yang ditampilkan lalu unggah
   dan periksa kembali. Jika valid, tinjau ringkasan dan klik
   **Terapkan ke skenario aktif**.
5. Periksa input yang tampil, kemudian klik **Jalankan Optimisasi**.

Satu workbook memuat seluruh input satu skenario. Impor mengganti input dan
menghapus hasil optimisasi lama pada skenario aktif; skenario lain dan riwayat
perbandingan tetap tersedia. File diperiksa tanpa menjalankan solver. Validasi
struktur/angka tidak menjamin model layak; diagnosis optimisasi tetap tersedia.
Mengganti file atau skenario setelah pemeriksaan mewajibkan pemeriksaan ulang.

| Sheet | Isi |
| --- | --- |
| Petunjuk | Panduan pengisian, satuan, aturan pewarisan tahun |
| Pengaturan | Tahun, periode, pilihan model, puncak dasar, pertumbuhan, karbon, diskonto, batas emisi, stokastik dan pilihan profil |
| Pembangkit | Nama, kapasitas dasar, investasi, O&M, biaya operasi, emisi, umur, ukuran blok, batas kapasitas |
| Kapasitas Eksogen | Opsional: tahun operasi, teknologi pembangkit, tambahan eksogen MW |
| Penyimpanan | Jenis, kapasitas awal, daya blok, durasi, efisiensi, batas daya, biaya dan umur |
| Beban Puncak | Puncak untuk setiap tahun setelah tahun dasar; wajib lengkap pada mode manual |
| Profil Beban | Tahun, jam 0–23, profil persen terhadap puncak; tahun dasar wajib lengkap |
| Availability | Tahun, jam, teknologi, availability 0–1; tahun dasar wajib lengkap untuk semua pembangkit |
| Stokastik | Nama skenario, probabilitas, nama parameter dan nilai; format panjang |

Profil khusus tahun berikutnya ditambahkan sebagai baris baru dan diaktifkan
melalui pilihan **Edit per tahun** di Pengaturan. Tahun tanpa data khusus tetap
mewarisi tahun dasar. Availability khusus boleh hanya memuat teknologi yang
diubah, tetapi setiap teknologi/tahun harus memiliki 24 jam lengkap.

Pada Stokastik, ulangi probabilitas yang sama pada baris-baris parameter satu
skenario. Jumlah probabilitas dihitung per skenario UNIK dan harus 1; setiap
skenario harus mengisi kumpulan parameter yang sama. Parameter harus sama dengan
nama pada katalog aplikasi untuk teknologi/model yang dipilih. Sheet ini boleh
hanya berisi header bila stokastik dinonaktifkan.

Nilai 60 pada Profil Beban berarti 60%; nilai 0,6 pada Availability berarti
60%; diskonto/pertumbuhan menggunakan angka persen biasa, misalnya 8 untuk 8%.
Angka langsung disarankan. Rumus harus sudah dihitung dan disimpan melalui Excel
agar hasilnya tersimpan dalam file; aplikasi tidak menjalankan rumus Excel.
Batas unggahan 10 MB, isi workbook setelah dibuka maksimum 50 MB.

Template berada di `templates/GENORA_template.xlsx`. Saat menyalin proyek atau
mengunggah ke GitHub/Streamlit Cloud, sertakan folder **templates**, modul
**excel_inputs.py**, **excel_ui.py**, serta requirements terbaru (openpyxl).
Node.js dan folder tools hanya dipakai untuk pembuatan template oleh pengembang;
aplikasi dan mahasiswa tidak memerlukan Node.js.

## Cakupan awal

### Skenario alternatif dari skenario dasar

Di sidebar **Kelola skenario**:

1. Atur input pada **Skenario dasar** sesuai sistem yang ingin dipelajari.
2. Buka **Tambah skenario dari dasar atau salinan lain**.
3. Pilih **Salin dari skenario**, masukkan nama unik, lalu klik **Tambah Skenario**.
4. Salinan menjadi skenario aktif. Ubah asumsi, misalnya harga karbon,
   pertumbuhan beban, biaya investasi, batas emisi, atau batas kapasitas teknologi.
5. Klik **Jalankan Optimisasi**. Gunakan **Skenario aktif** untuk berpindah dan
   lihat **Ringkasan seluruh skenario eksperimen** di bawah hasil.

Setiap skenario menyimpan pengaturan tahun, model, biaya/karbon, batas emisi,
tabel pembangkit, kapasitas tahun dasar, profil beban/ketersediaan, seluruh jenis
penyimpanan, serta parameter/probabilitas stokastik secara independen. Perubahan
otomatis disimpan selama sesi. Mengubah salinan tidak mengubah sumber; perubahan
pada sumber setelah penyalinan juga tidak diterapkan otomatis ke salinan.
Skenario baru menyalin INPUT, bukan hasil optimisasi. Jalankan optimisasi sendiri
untuk memperoleh hasilnya. Hasil lama tetap tersedia saat kembali ke skenario
yang sudah dihitung, jika inputnya belum berubah. Hasil yang tidak sesuai input
ditandai **Input berubah** dan dikeluarkan dari angka perbandingan terkini.

Skenario dapat disalin dari skenario dasar atau dari salinan lain. Nama harus
unik tanpa membedakan huruf besar/kecil. **Hapus skenario aktif** menghapus
salinan dari sesi dan kembali ke skenario dasar; skenario dasar tidak dapat
dihapus. Ringkasan perbandingan dapat diunduh sebagai CSV. Tombol **Simpan hasil
untuk perbandingan** tetap tersedia untuk menyimpan riwayat hasil secara manual.

Skenario eksperimen adalah kumpulan asumsi alternatif (misalnya Dasar, Karbon
tinggi, Baterai murah). Ini berbeda dari skenario ketidakpastian beserta
probabilitasnya di dalam satu model stokastik. Masing-masing skenario eksperimen
dapat menggunakan model deterministik atau stokastik sendiri.

Skenario, input, dan hasil disimpan dalam sesi browser, belum sebagai proyek
permanen. Sesi baru atau refresh yang memutus sesi dapat menghapus data tersebut;
unduh hasil yang ingin disimpan. Perbandingan biaya tahunan hanya bermakna jika
tahun akhir, model, dan asumsi tiap skenario dipertimbangkan.

Setelah mengubah input, tekan Enter atau klik sel lain untuk menyelesaikan edit,
termasuk **Profil beban (% terhadap beban puncak)** dan **Availability setiap
teknologi pembangkit**. Kedua tabel terpisah. Beban puncak tahun dasar diisi
di bagian profil beban; beban puncak tahun berikutnya mengikuti tabel proyeksi.
Tidak ada input beban puncak di sidebar.
Klik **Jalankan Optimisasi** di bawah bagian input. Perubahan input tidak
menjalankan solver secara otomatis. Hasil disimpan selama sesi dan tetap tampil
saat diunduh atau disimpan untuk perbandingan, tanpa perhitungan ulang.
Jika input/model/nama skenario berubah, hasil lama disembunyikan dengan pesan
agar dihitung ulang. Hasil lama tidak dapat diunduh atau disimpan sebagai hasil
input baru. Hasil yang sudah disimpan pada tabel perbandingan tetap tersedia.

- Kapasitas terpasang tahun dasar + pembangunan baru setiap tahun perencanaan.
- PLTU, PLTG, PLTS, PLTB; kapasitas kontinu (LP), blok integer (MILP), atau blok integer + baterai (MILP).
- Beban dan ketersediaan 24 jam yang dapat diedit; satu hari diulang 365 kali.
- Optimasi investasi yang ditahunkan, O&M tetap, operasi, dan karbon dengan SciPy/HiGHS.
- Keseimbangan daya wajib pada setiap jam, batas kapasitas, serta batas emisi opsional.
- Grafik kapasitas dan dispatch, ekspor CSV, perbandingan hasil selama sesi.
- Penjelasan persamaan tersedia pada tab Model matematika.

Data biaya, emisi, dan profil merupakan **ilustrasi**, bukan data aktual atau prakiraan.
Input investasi awal (USD/kW) terpisah dari input O&M tetap (USD/kW/tahun).
Pada hasil, biaya tetap adalah jumlah investasi yang ditahunkan dan O&M tetap.
Faktor 1.000 mengubah MW menjadi kW; setiap jam diberi bobot 365 untuk biaya operasi,
energi, dan emisi tahunan. Harga karbon tidak mengubah faktor emisi fisik.
Biaya rata-rata sistem termasuk biaya karbon, bukan tarif listrik.

Tidak ada transmisi, unit commitment pembangkit, ramping, cadangan, atau gangguan paksa.
Variasi musim dan keandalan tahunan belum terwakili.
Profil contoh ini tidak cocok untuk kesimpulan investasi nyata.

## Tahun dasar dan periode perencanaan

Atur di sidebar:

- **Tahun dasar**, yaitu tahun data beban dan kapasitas terpasang (default 2025).
- **Periode perencanaan (tahun)**, yaitu jarak dari tahun dasar ke tahun akhir
  (1–50 tahun, default 1). Tahun dasar 2025 + periode 5 tahun menghasilkan tahun akhir 2030.
- **Pertumbuhan beban tahunan (%)**, default 0%. Beban tahun akhir per jam
  dihitung dari `beban tahun dasar × (1 + g)^periode`, dengan g berupa pecahan.

Klik **Jalankan Optimisasi** setelah mengubah pengaturan. Tabel beban yang dapat
diedit menyimpan profil persentase dan availability TAHUN DASAR secara terpisah.
Proyeksi dibuat pada salinan, sehingga pertumbuhan tidak dihitung berulang saat
rerun. Secara default bentuk profil mengikuti tahun dasar.
Lihat **Proyeksi beban selama periode perencanaan** untuk puncak dan energi tiap
tahun. Tabel ini adalah proyeksi beban, bukan hasil optimisasi tahunan.

Pada bagian tersebut, **Metode proyeksi beban** menyediakan dua pilihan:
**Pertumbuhan tahunan** menggunakan persentase di sidebar; **Manual per tahun**
membuka tabel beban puncak yang dapat diedit untuk setiap tahun perencanaan.
Tahun dasar mengikuti tabel profil persen dan input puncak tahun dasar.
Energi tahunan dihitung dari profil tahun tersebut × puncak tahunan; energi
tidak diedit terpisah. Klik **Jalankan Optimisasi** setelah menyelesaikan edit.

### Profil beban dan availability berbeda per tahun

**Profil beban (% terhadap beban puncak)** berisi kolom Jam dan Profil beban
(% puncak). Masukkan nilai 0–100%, dan setidaknya satu jam harus 100%.
Persentase antarjam tidak harus berjumlah 100%. Beban aktual setiap jam:
`puncak_tahun × profil_persen_tahun / 100`. Input puncak tahun dasar berada
di bagian ini; puncak tahun berikutnya dihitung atau diedit pada proyeksi.

Pilih **Pola beban tahun berikutnya → Gunakan data tahun dasar** untuk memakai
pola yang sama pada semua tahun. Pilih **Edit per tahun**, lalu pilih
**Tahun profil beban yang diedit** untuk memasukkan pola khusus pada tahun itu.
Tahun yang belum memiliki profil khusus mengikuti tahun dasar.

**Availability setiap teknologi pembangkit** berisi Jam dan kolom per teknologi,
dengan nilai 0–1. Pilih **Availability tahun berikutnya → Gunakan data tahun
dasar** atau **Edit per tahun**, lalu pilih **Tahun availability yang diedit**.
Pengaturan ini independen dari pola beban. Teknologi baru pada tabel tahunan
mewarisi availability tahun dasar sampai diedit.

Mengembalikan pilihan ke **Gunakan data tahun dasar** mengabaikan seluruh data
khusus tahun berikutnya tanpa menghapusnya. Data khusus disimpan per tahun dan
per skenario eksperimen. Mengubah input aktif membuat hasil perlu dihitung ulang.
Proyeksi energi tahunan menjumlahkan beban dari profil tahun yang bersangkutan
dan mengalikannya dengan 365. Pada stokastik, faktor beban/availability skenario
diterapkan setelah profil setiap tahun dibentuk. Hasil dan diagnosis memakai
profil aktual tahun tersebut, termasuk ketika periode hanya satu tahun.
Input profil beban, beban aktual MW, dan availability semua tahun dapat diunduh
melalui **Unduh profil beban dan availability seluruh tahun CSV** setelah optimisasi.

Nilai manual disimpan per tahun dan per skenario eksperimen. Perubahan periode
mempertahankan nilai tahun yang sama; tahun tambahan diisi dari pertumbuhan
awal. Nilai yang sudah diedit tidak ditimpa ketika pertumbuhan berubah.
**Isi ulang dari pertumbuhan tahunan** secara eksplisit mengisi ulang nilai
manual. Dalam mode manual, pertumbuhan hanya dipakai untuk nilai awal/isi ulang;
solver menggunakan puncak manual. Faktor beban stokastik kemudian mengalikan
proyeksi manual tersebut. Mengganti metode kembali ke pertumbuhan mengabaikan
nilai manual tanpa menghapusnya. Hasil lama ditandai berubah setelah edit.

Periode lebih dari 1 tahun mengaktifkan **optimisasi multi tahun terpadu** untuk
LP, integer, dan stokastik. Tahun dasar 2025 dan periode 5 tahun mengoptimasi
2026, 2027, 2028, 2029, dan 2030 bersama-sama. Kapasitas kumulatif tidak boleh
turun. Selisih kapasitas antar tahun menentukan pembangunan baru; bukan
menjalankan optimisasi tiap tahun secara terpisah. Kapasitas baru tersedia sejak
tahun penambahannya. Aset lama maupun baru tetap tersedia sepanjang horizon.

Setiap tahun mempunyai dispatch 24 jam, proyeksi beban, batas emisi tahunan,
dan siklus penyimpanan harian sendiri. Pada stokastik, faktor skenario
mengalikan profil setiap tahun. Seluruh jadwal pembangunan merupakan keputusan
tahap pertama yang sama untuk semua skenario; dispatch berbeda menurut tahun
dan skenario. Belum ada keputusan investasi adaptif atau pohon multistage.
Biaya, ukuran blok, dan batas emisi konstan antar tahun; ketersediaan mengikuti
availability tahun dasar atau data khusus per tahun yang dipilih.
Batas kapasitas positif membatasi total kapasitas pada SETIAP tahun;
0 tetap berarti tanpa batas kapasitas pembangkit.

Fungsi tujuan multi tahun meminimalkan **nilai kini biaya tahunan ekuivalen**:
`sum_y biaya_tahunan[y] / (1+r)^y`, dengan tahun pertama y=1 (akhir tahun).
Biaya tahunan terdiri atas investasi CRF pada tambahan KUMULATIF, O&M tetap
seluruh kapasitas tersedia, operasi, dan karbon. Ini mempertahankan metode biaya
model satu tahun. Investasi awal dilaporkan hanya untuk penambahan tahun itu;
tidak ditambahkan lagi pada fungsi tujuan. Nilai kini ini bukan model arus kas
CAPEX di muka dengan nilai sisa. Umur aset menentukan CRF, bukan pensiun
otomatis. Belum ada nilai sisa eksplisit, penggantian aset, degradasi,
masa konstruksi, atau pensiun. Karena itu horizon melampaui umur aset perlu
ditafsirkan sesuai asumsi penyederhanaan ini.

Hasil menampilkan nilai kini biaya periode, tabel biaya/emisi tiap tahun,
tabel kapasitas awal tahun–penambahan–kapasitas akhir, jumlah blok baru,
investasi pembangunan, dan rencana penyimpanan. Pilih **Tahun untuk rincian
hasil dan dispatch** untuk melihat operasi dan biaya tahun tertentu.
CSV rencana pembangkit, penyimpanan, hasil tahunan dan seluruh dispatch dapat
diunduh. Grafik menampilkan tambahan dan kapasitas tersedia setiap tahun.
Tabel perbandingan skenario selalu memakai kapasitas/biaya tahunan tahun akhir
dan nilai kini seluruh periode, terlepas dari tahun rincian yang sedang dipilih.
Jika tidak layak, diagnosis mengidentifikasi tahun pertama yang bermasalah.

## Pilihan model kapasitas

Pilih **Kontinu (LP)** atau **Blok integer (MILP)** di sidebar. Pada model integer,
atur ukuran blok per teknologi pada tabel pembangkit. Nilai awal: PLTU 50 MW,
PLTG 25 MW, PLTS 10 MW, PLTB 10 MW. Kapasitas total K = kapasitas tahun dasar
+ ukuran blok × jumlah blok baru, dengan jumlah blok baru berupa bilangan bulat
tidak negatif. (Batas kapasitas total − kapasitas tahun dasar) dibagi ukuran blok
lalu dibulatkan ke bawah untuk menentukan jumlah blok baru maksimum.
Biaya tetap tetap dihitung dari kapasitas dalam MW, bukan jumlah blok saja.

Kedua model diselesaikan dengan HiGHS melalui `scipy.optimize.linprog`.
Mode integer mengaktifkan `integrality` hanya untuk jumlah blok; dispatch per jam
tetap kontinu. Ini adalah optimasi MILP, bukan pembulatan solusi LP dan bukan
unit commitment. Ringkasan integer dan CSV menyertakan ukuran serta jumlah blok.
Simpan hasil setiap mode untuk membandingkan biaya, kapasitas, dan emisi.

## Tambah teknologi dan biaya investasi

### Penambahan kapasitas eksogen

Buka **Penambahan kapasitas eksogen pembangkit** di bawah tabel pembangkit.
Tambahkan baris, isi **Tahun operasi**, **Teknologi**, dan **Tambahan eksogen
(MW)**, lalu klik **Jalankan Optimisasi**. Nama teknologi harus sudah ada pada
tabel pembangkit. Tahun operasi wajib berada setelah tahun dasar sampai tahun
akhir. Beberapa proyek dengan teknologi/tahun sama dijumlahkan. Tabel kosong
berarti tidak ada proyek. Fitur ini berlaku pada perencanaan satu/multi tahun,
LP, integer, dan stokastik; saat ini eksogen khusus pembangkit.

Kapasitas setiap tahun = kapasitas tahun dasar + eksogen kumulatif + endogen
kumulatif. Eksogen tersedia sejak tahun operasi dan tetap tersedia pada tahun
berikutnya. Endogen adalah tambahan yang dipilih solver. Eksogen tidak perlu
kelipatan blok; jumlah blok pada hasil hanya menghitung tambahan ENDOGEN.
Solver mengoptimasi seluruh jadwal dengan memperhitungkan proyek masa depan,
tanpa mengizinkan kapasitas tersebut memasok listrik sebelum tahun operasinya.

Batas positif membatasi total kapasitas dasar + eksogen + endogen. Karena
kapasitas endogen tidak dipensiunkan, pembangunan yang diperlukan lebih awal
dapat bertentangan dengan proyek eksogen yang masuk kemudian. Model mendeteksi
ketidaklayakan gabungan ini. Jadwal eksogen yang sudah melampaui batas total
ditolak sebagai input; nilai 0 pada batas tetap berarti tanpa batas kapasitas.

Investasi awal dilaporkan pada tahun penambahan eksogen/endogen. Investasi
yang ditahunkan (CRF) dan O&M eksogen masuk biaya sistem sejak tahun operasi,
dengan parameter biaya dan umur teknologi yang sama. Model tetap menggunakan
nilai kini biaya tahunan ekuivalen, bukan arus kas CAPEX di muka. Pada stokastik,
jadwal eksogen sama untuk semua skenario; biaya/profil dapat mengikuti parameter
ketidakpastian skenario. Angka hasil memisahkan eksogen, endogen, dan kumulatif.

Jadwal tersimpan per skenario eksperimen dan ikut disalin saat menambah skenario.
Penghapusan pembangkit membersihkan proyek eksogen terkait pada skenario aktif.
Template Excel terbaru menyertakan sheet **Kapasitas Eksogen** yang boleh kosong.
Workbook lama tanpa sheet ini tetap diterima sebagai tanpa kapasitas eksogen.

Klik **Hapus Teknologi**, pilih pembangkit atau penyimpanan tambahan, lalu
**Hapus dari skenario aktif** untuk menghapusnya. Pembangkit juga dihapus dari
availability tahun dasar dan seluruh tahun khusus. Parameter ketidakpastian
dan kolom skenario stokastik milik teknologi tersebut ikut dibersihkan;
probabilitas dan data teknologi lain dipertahankan. Hasil yang sudah dihitung
perlu dioptimasi ulang. Penghapusan hanya berlaku pada skenario aktif;
skenario sumber/salinan lain serta riwayat perbandingan tetap tersedia.

Setidaknya satu teknologi pembangkit harus tersisa. Baterai default tidak
berada pada tabel penyimpanan tambahan; untuk menonaktifkannya, atur daya
tahun dasar dan batas daya menjadi nol.

### Kapasitas terpasang pada tahun dasar

Isi **Kapasitas tahun dasar (MW)** pada tabel pembangkit, lalu klik
**Jalankan Optimisasi**. Nilai awal 0 mempertahankan contoh greenfield sebelumnya.
**Batas kapasitas (MW)** tetap merupakan batas TOTAL kapasitas lama + baru dan
bernilai **0 secara default, artinya tanpa batas kapasitas**. Jika diisi positif,
nilainya harus sekurangnya sebesar kapasitas tahun dasar. Contoh: aset lama 35 MW, blok
baru 10 MW, batas total 100 MW: penambahan maksimum 60 MW, total efektif 95 MW.
Kapasitas lama tidak perlu kelipatan blok. Pada model LP, penambahan bebas kontinu.

Investasi historis dianggap sunk cost dan tidak dihitung ulang. Investasi awal
dan investasi tahunan hanya untuk penambahan baru; O&M tetap untuk kapasitas
lama + baru. Biaya operasi dan emisi dihitung dari dispatch seluruh pembangkit.
Biaya sistem mencakup O&M aset lama meskipun tidak beroperasi. Grafik menumpuk
kapasitas tahun dasar dan penambahan; tabel/CSV juga mencantumkan kapasitas total.
Kolom **Jumlah blok** menyatakan jumlah blok BARU.

Pada penyimpanan, isi **Daya tahun dasar baterai (MW)** atau **Daya tahun dasar
(MW)** pada tabel jenis tambahan/formulir Tambah Teknologi. Batas daya juga batas
total lama + baru. Energi tahun dasar = daya tahun dasar × durasi; durasi dan
efisiensi berlaku bersama untuk aset lama dan baru pada jenis tersebut. Jika
karakteristik berbeda, masukkan sebagai jenis terpisah. Investasi daya/energi
hanya dikenai pada penambahan; O&M tetap pada seluruh daya/energi terpasang.

Berlaku untuk LP, blok integer, dan stokastik; kapasitas dasar sama pada semua
skenario dan hanya penambahan yang diputuskan pada tahap pertama. Diagnosis
memperhitungkan kapasitas dasar dan sisa batas pembangunan. Aset lama diasumsikan
tetap tersedia sepanjang tahun perencanaan: belum ada pensiun, sisa umur,
pelunasan investasi historis. Profil beban yang
diinput adalah beban tahun dasar; proyeksi beban mengikuti pengaturan periode
dan pertumbuhan di sidebar.

Klik **Tambah Teknologi**, isi formulir, lalu **Tambahkan ke model**. Masukkan nama
unik, investasi USD/kW, umur aset, O&M tetap, biaya variabel, emisi, batas kapasitas,
ukuran blok, dan profil ketersediaan awal (konstan atau contoh PLTS/PLTB).
Profil 24 jam dapat diedit pada bagian profil. Teknologi baru langsung masuk
ke optimisasi semua mode, grafik, CSV, perbandingan, dan diagnosis. Input lama
dipertahankan saat menambah teknologi. Batas kapasitas pembangkit **0 berarti
tanpa batas**, bukan menonaktifkan teknologi. Untuk meniadakan produksi, set
ketersediaannya menjadi nol pada seluruh jam. O&M tetap kapasitas lama tetap
diperhitungkan. Nilai positif membatasi total kapasitas lama + baru, termasuk
pembulatan sisa pembangunan pada model integer. Aturan ini berlaku untuk LP,
MILP, dan stokastik. Keseimbangan daya, ketersediaan, serta batas emisi tetap
berlaku meskipun batas kapasitas dihilangkan. Nilai batas positif yang sudah
diedit tidak diubah otomatis; ganti menjadi 0 bila ingin tanpa batas.

Aturan nol ini khusus **batas kapasitas pembangkit**. Batas daya penyimpanan
tetap memakai batas fisik positif untuk mode operasi biner; nol tetap berarti
tidak ada kapasitas penyimpanan yang dapat digunakan/dibangun.
Data disimpan selama sesi, bukan ke basis data permanen. Ini pembangkit dengan
profil ketersediaan; penambahan PLTA tidak otomatis membuat model reservoir.

Tingkat diskonto bersama di sidebar (default 8%) dan umur aset per teknologi
menentukan capital recovery factor: `CRF = r / (1 - (1+r)^(-L))` untuk r > 0,
dan `CRF = 1/L` untuk r = 0. Investasi awal = 1.000 × MW baru × investasi USD/kW.
Investasi tahunan = investasi awal × CRF. Biaya tetap tahunan = investasi tahunan
+ O&M tetap tahunan. Fungsi tujuan menjumlahkan biaya tetap, operasi, dan karbon;
investasi awal tidak ditambahkan lagi. Model multi tahun mendiskontokan biaya
tahunan ekuivalen ini dan mengoptimasi tambahan setiap tahun secara bersama.
Tidak ada nilai sisa atau jadwal penggantian aset.

CSV dan tabel hasil merinci investasi awal, investasi tahunan, O&M tetap, dan CRF.
Kolom biaya tetap sudah mencakup investasi tahunan + O&M tetap: jangan menjumlahkan
kolom rincian itu lagi. Nilai default investasi merupakan asumsi ilustratif baru,
sehingga hasil dasar dapat berbeda dari versi biaya tetap gabungan sebelumnya.

## Model blok integer + baterai

Pilih opsi ketiga di sidebar. Baterai dibangun dalam blok daya (default 10 MW)
dengan durasi tetap (default 4 jam), sehingga satu blok menyediakan 40 MWh.
Batas daya default 200 MW. Semua parameter ini dapat diubah.

Model mengoptimasi jumlah blok, pengisian, pelepasan, dan energi tersimpan setiap jam.
Keseimbangan node: pembangkitan + pelepasan = beban + pengisian.
Energi pada batas jam berikutnya = energi sekarang + eta_isi × pengisian
− pelepasan / eta_keluar, untuk langkah 1 jam. Kedua eta adalah akar efisiensi
round-trip (default 90%). Energi awal dioptimasi dan wajib sama dengan energi akhir
hari. Bobot 365 hanya diterapkan pada energi dan biaya tahunan, bukan dinamika SOC.
Variabel biner per jam mencegah pengisian dan pelepasan bersamaan.

Investasi awal baterai = 1.000 × (MW × investasi daya USD/kW + MWh × investasi energi
USD/kWh). Investasi tersebut ditahunkan dengan CRF menurut umur baterai (default
15 tahun) dan diskonto bersama. Biaya tetap baterai = investasi tahunan +
1.000 × (MW × O&M daya USD/kW/tahun + MWh × O&M energi USD/kWh/tahun).
Gunakan komponen biaya daya/energi yang tidak tumpang tindih.
Biaya operasi dikenakan per MWh energi keluar. Baterai boleh diisi dari semua
pembangkit; emisi sudah dihitung pada pembangkitan pengisiannya, tanpa dihitung
ulang saat pelepasan. Degradasi, self-discharge, dan variasi musim belum dimodelkan.

Grafik menampilkan kapasitas daya baterai, dispatch dengan pengisian negatif
di bawah nol dan pelepasan positif (garis beban tetap menunjukkan kebutuhan listrik),
energi tersimpan (MWh) pada batas jam 0–24, dan daya isi/keluar. Tabel terpisah
merangkum biaya, energi masuk/keluar, dan rugi energi tahunan. CSV dispatch
menyertakan energi awal/akhir setiap jam; ringkasan baterai dapat diekspor terpisah.
Kapasitas nol adalah hasil yang valid jika baterai tidak ekonomis atau tidak dibutuhkan.

## Menambahkan beberapa teknologi penyimpanan

Klik **Tambah Teknologi**, pilih **Penyimpanan energi** pada **Jenis teknologi baru**,
isi nama dan parameter, lalu klik **Tambahkan penyimpanan ke model**. Aplikasi
otomatis memilih **Blok integer + penyimpanan (MILP)**. Baterai default tetap
tersedia; ubah daya tahun dasar dan batas dayanya menjadi nol jika tidak ingin menggunakannya.

Setiap jenis tambahan memiliki daya blok (MW), durasi (jam), batas daya (MW),
efisiensi round-trip, investasi daya/energi, O&M daya/energi, biaya per MWh keluar,
dan umur aset sendiri. Parameter dapat diedit pada tabel penyimpanan tambahan;
efisiensi di tabel dinyatakan sebagai pecahan 0–1. Nilai form adalah ilustrasi,
bukan data teknologi nyata. Nama harus unik dan berbeda dari pembangkit atau
nama kolom sistem. Data dan edit yang sudah ada tetap dipertahankan.

Model menentukan jumlah blok setiap jenis secara terpisah. Masing-masing
memiliki batas daya, kapasitas energi, SOC, keseimbangan energi, siklus harian,
dan biner mode isi/keluar sendiri. Keseimbangan node menjumlahkan operasi seluruh
jenis. Pertukaran listrik antarjenis hanya melalui node; kapasitas energi tidak
dapat dipinjam antarjenis. Semua biaya investasi dan operasi dijumlahkan sekali.

Grafik dispatch memisahkan isi negatif dan keluar positif per jenis. Pilih jenis
melalui **Penyimpanan untuk grafik energi** untuk SOC dan operasi detail.
Ringkasan serta CSV menyertakan semua jenis, daya, energi, biaya, dan rugi energi.
CSV dispatch memuat kolom per jenis (misalnya `Flow · Isi (MW)`) serta kolom total.
Kolom `Isi baterai (MW)` / `Keluar baterai (MW)` pada CSV adalah total seluruh
penyimpanan untuk kompatibilitas. Ringkasan perbandingan menyimpan rincian semua jenis.

Pada model stokastik, kapasitas SETIAP jenis ditautkan antar skenario, sementara
operasi dan SOC masing-masing mengikuti skenario. Diagnosis dapat mengusulkan
perubahan daya atau durasi jenis tertentu, dengan uji kelayakan ulang.
Model kontinu dan blok integer tanpa penyimpanan mengabaikan katalog penyimpanan
secara sengaja; data katalog tetap tersimpan untuk saat mode penyimpanan diaktifkan.

Pumped hydro, baterai aliran, dan nama lainnya memakai model penyimpanan listrik
generik yang sama. Nama tidak menambahkan aliran air alami, batas reservoir
musiman, degradasi, self-discharge, atau model elektrokimia khusus.

## Verifikasi

### Model stokastik dua tahap

Centang **Aktifkan model stokastik dua tahap** di sidebar, pilih model kapasitas
yang diinginkan, lalu edit tabel skenario dan klik **Jalankan Optimisasi**.
Model tersedia untuk kapasitas kontinu, blok integer, serta integer + penyimpanan.

Gunakan **Parameter yang tidak pasti** untuk memilih kolom ketidakpastian, dan
**Jumlah skenario ketidakpastian** untuk memilih 2–50 skenario (termasuk 2, 3, 4,
atau lebih). Nama skenario dan semua nilai pada tabel dapat diubah. Probabilitas
harus positif dan berjumlah 1; tombol **Samakan probabilitas skenario** mengisi
1/N untuk seluruh baris. Saat jumlah skenario berubah, nilai baris yang tersisa
dipertahankan dan probabilitas diatur merata dengan pemberitahuan. Baris baru
diisi nilai dasar, sehingga pengguna dapat menentukan variasinya sendiri.

Pilihan parameter mencakup faktor beban; faktor ketersediaan tiap pembangkit;
investasi, O&M tetap, biaya variabel, faktor emisi, dan umur aset per pembangkit;
harga karbon; tingkat diskonto; batas emisi jika diaktifkan; serta investasi,
O&M, biaya operasi, umur aset, dan efisiensi per teknologi penyimpanan.
Teknologi baru otomatis masuk katalog pilihan. Ukuran blok, batas pembangunan,
dan durasi penyimpanan tidak diacak karena merupakan spesifikasi desain tetap.

Hanya kolom parameter yang dipilih digunakan dalam model. Parameter yang tidak
dipilih menggunakan nilai dasar, meskipun pernah memiliki nilai skenario yang
berbeda. Nilai kolom lama disimpan selama sesi dan muncul kembali bila dipilih
lagi. Kolom **Faktor** adalah pengali profil dasar; hasil ketersediaan dibatasi
maksimum 1. Kolom lain berisi nilai aktual sesuai satuan judul (misalnya biaya
85 USD/MWh, bukan faktor 85). Efisiensi penyimpanan pada tabel skenario dalam %.

Probabilitas melekat pada skenario gabungan (satu baris), bukan distribusi
independen setiap parameter. Korelasi antarnilai dapat direpresentasikan dengan
kombinasi baris yang dibuat pengguna. Tiga skenario/probabilitas awal hanyalah
ilustrasi pembelajaran, bukan estimasi distribusi empiris. Tidak ada pembentukan
otomatis semua kombinasi distribusi marginal atau pengambilan sampel Monte Carlo.

Tahap pertama memilih kapasitas pembangkit dan jumlah blok baterai **bersama**
untuk seluruh skenario (non-anticipativity). Tahap kedua menentukan dispatch,
pengisian, pelepasan, dan energi baterai untuk tiap skenario. Fungsi tujuan adalah
penjumlahan berbobot probabilitas atas biaya tetap + operasi + karbon per skenario.
Jika parameter biaya tetap tidak diacak, pembobotan menghitung biaya tetap sekali.
Jika investasi, umur, atau diskonto diacak, CRF dan biaya dihitung per skenario
terlebih dahulu, kemudian dibobot; CRF bukan dihitung dari rata-rata diskonto.
Investasi awal yang ditampilkan juga berupa ekspektasi jika biaya investasi tidak pasti.
Semua beban dan batas emisi wajib dipenuhi pada **setiap** skenario,
bukan hanya pada rata-rata. Siklus energi baterai tertutup pada setiap skenario.

Model risk-neutral ini mengasumsikan seluruh profil 24 jam pada skenario diketahui
saat dispatch tahap kedua ditentukan. Ini bukan optimisasi multistage, rolling
forecast, CVaR, atau chance constraints. Kapasitas harus melayani seluruh skenario
yang dimasukkan, tetapi tidak memberikan jaminan untuk skenario di luar tabel.

Hasil utama menunjukkan biaya, produksi, throughput baterai, dan emisi ekspektasian.
Rasio biaya per MWh adalah biaya ekspektasian / energi beban ekspektasian.
Pilih skenario pada dropdown untuk grafik dispatch dan SOC yang sesuai;
grafik tidak mencampurkan jadwal dari skenario berbeda. CSV tersedia untuk input
skenario, metrik tiap skenario, dan seluruh dispatch. Tabel perbandingan menyimpan
pendekatan dan skenario yang digunakan. Perubahan tabel skenario menandai hasil
lama perlu dihitung ulang; pemilihan grafik saja tidak menjalankan solver.

Jika infeasible, diagnosis tersedia untuk tiap skenario bermasalah. Saran perubahan
parameter dalam diagnosis hanya teruji untuk **skenario yang dipilih**, belum untuk
seluruh model stokastik. Jika parameter dipilih sebagai tidak pasti, ubah nilainya
di baris skenario terkait; mengubah nilai dasar tidak mengganti nilai skenario.
Model gabungan dibatasi 30 detik; hasil yang belum terbukti
optimal tidak ditampilkan sebagai solusi optimum.

### Diagnosis ketika model tidak layak

Setelah tombol optimisasi ditekan, status infeasible memicu pemeriksaan otomatis:

- Batas pasokan per jam berdasarkan kapasitas efektif (pembulatan ke bawah pada model blok).
- Minimum total energi tidak terlayani dengan slack beban, menggunakan batas emisi,
  dinamika baterai, dan aturan integer yang sama. Ini hanya alat diagnosis; jam
  kekurangan dapat berbeda antar solusi diagnosis yang sama-sama optimal.
- Emisi minimum dengan batas emisi dilepas, tetapi kendala fisik tetap berlaku.
- Contoh perubahan satu parameter: batas kapasitas pembangkit, ukuran blok,
  batas emisi, batas daya atau durasi baterai. Saran numerik hanya ditampilkan jika
  penyelesaian ulang membuktikan perubahan tersebut layak dengan parameter lain tetap.

Contoh saran tidak selalu merupakan perubahan terkecil atau paling murah, dan tidak
diterapkan otomatis. Pemeriksaan diagnosis dibatasi 5 detik per percobaan; bila
belum selesai, aplikasi menyatakannya tanpa mengklaim hasil optimal. Jika beberapa
kendala perlu diubah bersamaan, pemeriksaan satu parameter mungkin tidak menemukan
perbaikan. Ini bukan pencarian IIS (minimal conflicting constraint set).
Mengubah biaya atau harga karbon saja tidak memperbaiki infeasibilitas.

```powershell
.\.venv\Scripts\python -m unittest -v
```

Pengujian mencakup keseimbangan daya, batas produksi, perhitungan biaya,
solusi analitis satu pembangkit, batas emisi, dan kasus tidak layak.

Referensi API: [SciPy linprog](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html)
dan [Streamlit](https://docs.streamlit.io/).
