# Modbus TCP/RTU Cihaz İzleme ve Veri Aktarım Sistemi

Bu proje, Modbus TCP ve Modbus RTU protokolleriyle haberleşen endüstriyel cihazlardan ölçüm verilerinin alınmasını, kaydedilmesini, izlenmesini ve farklı aktarım yöntemleriyle gönderilmesini sağlayan yapılandırılabilir bir cihaz izleme sistemidir.

Sistem belirli bir inverter modeline bağlı kalmadan farklı Modbus cihazlarının eklenmesine ve yönetilmesine olanak sağlayacak şekilde geliştirilmiştir. Cihaz bağlantı bilgileri, Unit ID, register adresi, Function Code, veri tipi, ölçek katsayısı ve ölçüm birimi gibi bilgiler kullanıcı tarafından yapılandırılabilir.

## Temel Özellikler

- Modbus TCP ve Modbus RTU haberleşmesi
- Kod tabanlı TCP ve RTU cihaz simülasyonu
- Çoklu cihaz ve çoklu ölçüm desteği
- Otomatik polling sistemi
- SQLite veritabanında veri saklama
- Anlık ölçüm ve geçmiş kayıtlarının ayrı tutulması
- Cihaz sağlık ve bağlantı durumu takibi
- 30 günlük ölçüm geçmişi saklama politikası
- Web tabanlı cihaz yönetimi
- Cihaz ekleme, düzenleme, silme ve devre dışı bırakma
- Cihaz kopyalama ve CSV ile toplu cihaz ekleme
- Register adresi ve register adedi güncelleme
- CSV ve JSON formatında veri dışa aktarma
- FTP, SFTP ve JSON API aktarımı
- Başarılı ve başarısız aktarım geçmişinin tutulması
- Hatalı bağlantılar için açıklayıcı hata mesajları

## Sistem Akışı

```text
Cihaz Tanımı
     ↓
Modbus TCP/RTU Adapteri
     ↓
Polling ile Veri Okuma
     ↓
SQLite Veritabanı
     ↓
Web Arayüzü
     ↓
FTP / SFTP / JSON API Aktarımı
```
