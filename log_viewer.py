import sys
import re
import paramiko
import requests
import folium
import os
import pandas as pd
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QLabel, QTableWidget, QTableWidgetItem, QMessageBox,
    QFileDialog, QHeaderView
)
from PyQt5.QtCore import QTimer
from PyQt5.QtMultimedia import QSound  # Sesli uyarı için

# Log regex deseni
log_pattern = re.compile(
    r'(?P<ip>\d+\.\d+\.\d+\.\d+)\s-\s-\s\[(?P<date>.*?)\]\s"(?P<method>\w+)\s(?P<path>.*?)\s(?P<protocol>.*?)"\s(?P<status>\d+)\s(?P<size>\d+)\s"(?P<referrer>.*?)"\s"(?P<agent>.*?)"'
)

class LogViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🌐 Sunucu HTTP İstek Takibi")
        self.resize(1200, 700)

        self.ssh_client = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_logs)

        self.geo_cache = {}  # IP adresleri için coğrafi konum önbelleği
        self.map = folium.Map(location=[0, 0], zoom_start=2)
        self.map_file = "ip_map.html"
        self.seen_logs = set()  # Aynı log satırlarının tekrarını engellemek için

        layout = QVBoxLayout()

        # Giriş alanları
        form_layout = QHBoxLayout()
        self.ip_edit = QLineEdit("127.0.0.1")
        self.port_edit = QLineEdit("22")
        self.user_edit = QLineEdit("root")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)

        for label, widget in zip(
            ["IP", "Port", "Kullanıcı", "Şifre"],
            [self.ip_edit, self.port_edit, self.user_edit, self.pass_edit]
        ):
            form_layout.addWidget(QLabel(label))
            form_layout.addWidget(widget)

        layout.addLayout(form_layout)

        # Bağlantı ve diğer butonlar
        button_layout = QHBoxLayout()
        self.connect_btn = QPushButton("🔌 Bağlan")
        self.connect_btn.clicked.connect(self.toggle_connection)
        button_layout.addWidget(self.connect_btn)

        self.export_csv_btn = QPushButton("📁 Dışa Aktar (CSV)")
        self.export_csv_btn.clicked.connect(self.export_csv)
        button_layout.addWidget(self.export_csv_btn)

        self.export_excel_btn = QPushButton("📁 Dışa Aktar (Excel)")
        self.export_excel_btn.clicked.connect(self.export_excel)
        button_layout.addWidget(self.export_excel_btn)

        self.clear_btn = QPushButton("🧹 Temizle")
        self.clear_btn.clicked.connect(self.clear_table)
        button_layout.addWidget(self.clear_btn)

        self.map_btn = QPushButton("🗺️ Haritayı Göster")
        self.map_btn.clicked.connect(self.show_map)
        button_layout.addWidget(self.map_btn)

        layout.addLayout(button_layout)

        # Log tablosu
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "IP", "Ülke", "Şehir", "Tarih", "Yöntem", "Yol", "Durum", "Boyut", "Referrer", "User-Agent"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        self.setLayout(layout)

    def toggle_connection(self):
        if self.ssh_client:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        ip = self.ip_edit.text()
        port = int(self.port_edit.text())
        user = self.user_edit.text()
        password = self.pass_edit.text()

        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.ssh_client.connect(ip, port=port, username=user, password=password, timeout=10)
            self.connect_btn.setText("❌ Bağlantıyı Kes")
            self.add_log_row(["🟢 Bağlantı sağlandı.", "", "", "", "", "", "", "", "", ""])
            self.timer.start(3000)
        except Exception as e:
            self.ssh_client = None
            QMessageBox.critical(self, "Hata", str(e))

    def disconnect(self):
        if self.ssh_client:
            self.ssh_client.close()
            self.ssh_client = None
            self.timer.stop()
            self.connect_btn.setText("🔌 Bağlan")
            self.add_log_row(["🔴 Bağlantı kesildi.", "", "", "", "", "", "", "", "", ""])

    def update_logs(self):
        try:
            command = "tail -n 10 /var/log/nginx/access.log"
            stdin, stdout, stderr = self.ssh_client.exec_command(command)
            output = stdout.read().decode()
            if output:
                for line in output.strip().split('\n'):
                    if line in self.seen_logs:
                        continue  # Aynı logu tekrar ekleme
                    self.seen_logs.add(line)

                    match = log_pattern.search(line)
                    if match:
                        ip = match.group("ip")
                        date = match.group("date")
                        method = match.group("method")
                        path = match.group("path")
                        status = match.group("status")
                        size = match.group("size")
                        referrer = match.group("referrer")
                        agent = match.group("agent")

                        # GeoIP bilgisi al
                        country, city, lat, lon = self.get_geo_info(ip)

                        # Haritaya marker ekle
                        if lat and lon:
                            folium.Marker(
                                location=[lat, lon],
                                popup=f"{ip} - {city}, {country}",
                                icon=folium.Icon(color="red" if status in ["403", "404", "500"] else "blue")
                            ).add_to(self.map)
                            self.map.save(self.map_file)



                        self.add_log_row([
                            ip, country, city, date, method, path, status, size, referrer, agent
                        ])
        except Exception as e:
            self.add_log_row([f"Hata: {e}", "", "", "", "", "", "", "", "", ""])
            self.disconnect()

    def get_geo_info(self, ip):
        if ip in self.geo_cache:
            return self.geo_cache[ip]
        try:
            response = requests.get(f"http://ip-api.com/json/{ip}").json()
            country = response.get("country", "")
            city = response.get("city", "")
            lat = response.get("lat", None)
            lon = response.get("lon", None)
            self.geo_cache[ip] = (country, city, lat, lon)
            return country, city, lat, lon
        except:
            return "", "", None, None

    def add_log_row(self, data):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, item in enumerate(data):
            self.table.setItem(row, col, QTableWidgetItem(item))

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "CSV olarak kaydet", "", "CSV Dosyaları (*.csv)")
        if path:
            data = []
            for row in range(self.table.rowCount()):
                row_data = []
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    row_data.append(item.text() if item else "")
                data.append(row_data)
            df = pd.DataFrame(data, columns=[
                "IP", "Ülke", "Şehir", "Tarih", "Yöntem", "Yol", "Durum", "Boyut", "Referrer", "User-Agent"
            ])
            df.to_csv(path, index=False)
            QMessageBox.information(self, "Başarılı", "Veriler CSV dosyasına kaydedildi.")

    def export_excel(self):
        path, _ = QFileDialog.getSaveFileName(self, "Excel olarak kaydet", "", "Excel Dosyaları (*.xlsx)")
        if path:
            data = []
            for row in range(self.table.rowCount()):
                row_data = []
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    row_data.append(item.text() if item else "")
                data.append(row_data)
            df = pd.DataFrame(data, columns=[
                "IP", "Ülke", "Şehir", "Tarih", "Yöntem", "Yol", "Durum", "Boyut", "Referrer", "User-Agent"
            ])
            df.to_excel(path, index=False)
            QMessageBox.information(self, "Başarılı", "Veriler Excel dosyasına kaydedildi.")

    def clear_table(self):
        self.table.setRowCount(0)
        self.map = folium.Map(location=[0, 0], zoom_start=2)
        self.geo_cache.clear()
        self.seen_logs.clear()
        if os.path.exists(self.map_file):
            os.remove(self.map_file)

    def show_map(self):
        if os.path.exists(self.map_file):
            os.startfile(self.map_file)  # Windows için
            # macOS/Linux için alternatif:
            # import webbrowser
            # webbrowser.open(self.map_file)
        else:
            QMessageBox.warning(self, "Uyarı", "Harita dosyası bulunamadı.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LogViewer()
    window.show()
    sys.exit(app.exec_())
