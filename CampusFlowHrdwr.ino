#include <ESP8266WiFi.h>
#include <ESP8266WiFiMulti.h> 
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>

ESP8266WiFiMulti wifiMulti;

// --- CONFIGURATION ---
const char* studentID = "V7";      
const char* serverUrl = "http://cusjd-2401-4900-4e10-34-4d94-3ea7-3f3a-ba6d.a.free.pinggy.link/update_location";

const unsigned long SCAN_INTERVAL = 20000; 
unsigned long lastScanTime = 0;
bool isScanning = false;

// --- HELPER: FILTER MOBILE HOTSPOTS ---
bool shouldIgnore(String bssid, String ssidName) {
  String lowerSSID = ssidName;
  lowerSSID.toLowerCase();
  if (lowerSSID.indexOf("meghasravan") >= 0 || lowerSSID.indexOf("airfiber") >= 0) return false; 
  
  if (bssid.length() < 2) return true;
  char secondChar = bssid.charAt(1);
  if (secondChar == '2' || secondChar == '6' || secondChar == 'A' || 
      secondChar == 'a' || secondChar == 'E' || secondChar == 'e') {
    return true; 
  }
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(1000); 
  
  Serial.println("\n--- [STEP 1] SYSTEM STARTING ---");
  
  WiFi.mode(WIFI_STA);
  WiFi.setSleepMode(WIFI_NONE_SLEEP);

  // Register Access Points
  wifiMulti.addAP("Samsung galaxy m32", "25072005");
  wifiMulti.addAP("CMRTC-133", "1234567A");
  wifiMulti.addAP("CSE_STAFF_217", "Cse12345@");
  wifiMulti.addAP("CSE-HOD", "@cse1234567");
  wifiMulti.addAP("CSEAIML129", "1234567a");
  wifiMulti.addAP("ECE STAFF ROOM", "1234567a");
  wifiMulti.addAP("Vivo", "Oct2025@");
  wifiMulti.addAP("STAFF ROOM 240", "1234567a");
  wifiMulti.addAP("AndriodAP_7051", "1234567a");
  wifiMulti.addAP("AndriodAP_1331", "1234567a");
  
  Serial.println("--- [STEP 2] AP LIST REGISTERED ---");
}

void loop() {
  // HIDDEN TASK: WiFiMulti handles the "handshake" and re-connection in the background
  uint8_t status = wifiMulti.run();

  if (status == WL_CONNECTED) {
    static String lastSSID = "";
    if (WiFi.SSID() != lastSSID) {
      Serial.printf("\n[CONNECTED] Successfully joined: %s (IP: %s)\n", WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
      lastSSID = WiFi.SSID();
    }

    if (millis() - lastScanTime >= SCAN_INTERVAL && !isScanning) {
      WiFi.scanNetworks(true, true); // true, true = Async scan, show hidden networks
      isScanning = true;
      Serial.println("\n[SCAN] Starting background environment lookup...");
    }
  } else {
    Serial.print("."); // Still trying to find a registered router
    delay(500);
  }

  int n = WiFi.scanComplete();
  if (n >= 0 && isScanning) {
    Serial.printf("[SCAN] Completed. Found %d total networks nearby.\n", n);
    processScanResults(n);
    isScanning = false;
    lastScanTime = millis();
    WiFi.scanDelete(); 
  }
}

void processScanResults(int n) {
  int strongestRSSI = -100;
  String strongestBSSID = "";
  String strongestSSID = "";

  Serial.println("--- [ANALYSIS] Evaluating Signals ---");
  for (int i = 0; i < n; ++i) {
    String ssid = WiFi.SSID(i);
    int rssi = WiFi.RSSI(i);
    String bssid = WiFi.BSSIDstr(i);

    // Show the hidden task of checking each network
    if (shouldIgnore(bssid, ssid)) {
      // Serial.printf("  Ignoring: %s (Randomized/Mobile Hotspot)\n", ssid.c_str());
      continue;
    }

    Serial.printf("  Valid: %s | Strength: %d dBm\n", (ssid == "" ? "[Hidden]" : ssid.c_str()), rssi);

    if (rssi > strongestRSSI) {
      strongestRSSI = rssi;
      strongestBSSID = bssid;
      strongestSSID = ssid;
    }
  }

  if (strongestBSSID != "") {
    Serial.printf("--- [WINNER] Strongest Router: %s (%d dBm) ---\n", strongestSSID.c_str(), strongestRSSI);
    if (WiFi.status() == WL_CONNECTED) {
      sendToServer(strongestBSSID, strongestSSID, strongestRSSI);
    }
  } else {
    Serial.println("[!] No valid campus routers found in range.");
  }
}

void sendToServer(String bssid, String ssid, int rssi) {
  WiFiClient client;
  HTTPClient http;
  
  http.setTimeout(8000); 
  if (http.begin(client, serverUrl)) {
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");
    http.addHeader("x-pinggy-no-screen", "true"); 
    
    String postData = "student_id=" + String(studentID) + 
                      "&bssid=" + bssid + 
                      "&ssid=" + ssid + 
                      "&rssi=" + String(rssi);

    Serial.printf("[HTTP] Transmitting location data for %s...", studentID);
    int httpCode = http.POST(postData);
    
    if (httpCode > 0) {
      Serial.printf(" SUCCESS. Server Response: %d\n", httpCode);
    } else {
      Serial.printf(" FAILED. Error: %s\n", http.errorToString(httpCode).c_str());
    }
    http.end();
  }
}