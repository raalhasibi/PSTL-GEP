# Lab Kapasitas Pembangkit

Aplikasi Python berbahasa Indonesia untuk pembelajaran perencanaan kapasitas satu node.

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

## Cakupan awal

Setelah mengubah input, tekan Enter atau klik sel lain untuk menyelesaikan edit,
lalu klik **Jalankan Optimisasi** di bawah bagian input. Perubahan input tidak
menjalankan solver secara otomatis. Hasil disimpan selama sesi dan tetap tampil
saat diunduh atau disimpan untuk perbandingan, tanpa perhitungan ulang.
Jika input/model/nama skenario berubah, hasil lama disembunyikan dengan pesan
agar dihitung ulang. Hasil lama tidak dapat diunduh atau disimpan sebagai hasil
input baru. Hasil yang sudah disimpan pada tabel perbandingan tetap tersedia.

- Seluruh pembangkit dibangun baru (greenfield), satu tahun perencanaan.
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

## Pilihan model kapasitas

Pilih **Kontinu (LP)** atau **Blok integer (MILP)** di sidebar. Pada model integer,
atur ukuran blok per teknologi pada tabel pembangkit. Nilai awal: PLTU 50 MW,
PLTG 25 MW, PLTS 10 MW, PLTB 10 MW. Kapasitas K = ukuran blok × jumlah blok,
dengan jumlah blok berupa bilangan bulat tidak negatif. Batas kapasitas dibagi
ukuran blok lalu dibulatkan ke bawah untuk menentukan jumlah blok maksimum.
Biaya tetap tetap dihitung dari kapasitas dalam MW, bukan jumlah blok saja.

Kedua model diselesaikan dengan HiGHS melalui `scipy.optimize.linprog`.
Mode integer mengaktifkan `integrality` hanya untuk jumlah blok; dispatch per jam
tetap kontinu. Ini adalah optimasi MILP, bukan pembulatan solusi LP dan bukan
unit commitment. Ringkasan integer dan CSV menyertakan ukuran serta jumlah blok.
Simpan hasil setiap mode untuk membandingkan biaya, kapasitas, dan emisi.

## Tambah teknologi dan biaya investasi

Klik **Tambah Teknologi**, isi formulir, lalu **Tambahkan ke model**. Masukkan nama
unik, investasi USD/kW, umur aset, O&M tetap, biaya variabel, emisi, batas kapasitas,
ukuran blok, dan profil ketersediaan awal (konstan atau contoh PLTS/PLTB).
Profil 24 jam dapat diedit pada bagian profil. Teknologi baru langsung masuk
ke optimisasi semua mode, grafik, CSV, perbandingan, dan diagnosis. Input lama
dipertahankan saat menambah teknologi. Batas kapasitas nol menonaktifkan teknologi.
Data disimpan selama sesi, bukan ke basis data permanen. Ini pembangkit dengan
profil ketersediaan; penambahan PLTA tidak otomatis membuat model reservoir.

Tingkat diskonto bersama di sidebar (default 8%) dan umur aset per teknologi
menentukan capital recovery factor: `CRF = r / (1 - (1+r)^(-L))` untuk r > 0,
dan `CRF = 1/L` untuk r = 0. Investasi awal = 1.000 × MW × investasi USD/kW.
Investasi tahunan = investasi awal × CRF. Biaya tetap tahunan = investasi tahunan
+ O&M tetap tahunan. Fungsi tujuan menjumlahkan biaya tetap, operasi, dan karbon;
investasi awal tidak ditambahkan lagi. Model tetap satu tahun representatif,
bukan optimisasi ekspansi multiyear. Tidak ada nilai sisa atau jadwal penggantian aset.

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
tersedia; ubah batas dayanya menjadi nol jika tidak ingin menggunakannya.

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
