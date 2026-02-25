import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;
import Toybox.Time;
import Toybox.Time.Gregorian;
import Toybox.ActivityMonitor;
import Toybox.Activity;

//! Hlavní view ciferníku Home Dashboard.
//! Zobrazuje čas, datum, den v týdnu, baterii, kroky, tep a stav Bluetooth.
class HomeDashboardView extends WatchUi.WatchFace {

    // České názvy dnů v týdnu (1=neděle, 2=pondělí, ..., 7=sobota)
    private var _dnyVTydnu as Array<String> = [
        "Ne", "Po", "Út", "St", "Čt", "Pá", "So"
    ];

    // České názvy měsíců
    private var _mesice as Array<String> = [
        "led", "úno", "bře", "dub", "kvě", "čvn",
        "čvc", "srp", "zář", "říj", "lis", "pro"
    ];

    function initialize() {
        WatchFace.initialize();
    }

    function onLayout(dc as Dc) as Void {
    }

    function onShow() as Void {
    }

    //! Hlavní vykreslovací metoda — volá se každou minutu (nebo sekundu v aktivním režimu).
    function onUpdate(dc as Dc) as Void {
        var width = dc.getWidth();
        var height = dc.getHeight();

        // Pozadí
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        // Získání aktuálního času
        var clockTime = System.getClockTime();
        var now = Time.now();
        var info = Gregorian.info(now, Time.FORMAT_SHORT);

        // --- ČAS ---
        var hours = clockTime.hour;
        if (!System.getDeviceSettings().is24Hour) {
            if (hours > 12) {
                hours = hours - 12;
            } else if (hours == 0) {
                hours = 12;
            }
        }

        var timeStr = Lang.format("$1$:$2$", [
            hours.format("%02d"),
            clockTime.min.format("%02d")
        ]);

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            width / 2,
            height / 2 - 40,
            Graphics.FONT_NUMBER_HOT,
            timeStr,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER
        );

        // --- DATUM ---
        // info.day_of_week: 1=Ne, 2=Po, 3=Út, 4=St, 5=Čt, 6=Pá, 7=So
        var dayIdx = info.day_of_week as Number;
        var monthIdx = info.month as Number;

        var dayName = "?";
        if (dayIdx >= 1 && dayIdx <= 7) {
            dayName = _dnyVTydnu[dayIdx - 1];
        }

        var monthName = "?";
        if (monthIdx >= 1 && monthIdx <= 12) {
            monthName = _mesice[monthIdx - 1];
        }

        var dateStr = Lang.format("$1$ $2$. $3$", [
            dayName,
            info.day.format("%d"),
            monthName
        ]);

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            width / 2,
            height / 2 + 20,
            Graphics.FONT_SMALL,
            dateStr,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER
        );

        // --- BATERIE ---
        var battery = System.getSystemStats().battery;
        var battStr = Lang.format("$1$%", [battery.format("%d")]);

        dc.setColor(getBatteryColor(battery), Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            width / 2 - 50,
            height / 2 + 55,
            Graphics.FONT_TINY,
            battStr,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER
        );

        // Ikona baterie (jednoduchý obdélník)
        drawBatteryIcon(dc, width / 2 - 75, height / 2 + 48, battery);

        // --- KROKY ---
        var actInfo = ActivityMonitor.getInfo();
        var steps = actInfo.steps;
        var stepsStr = steps.format("%d");

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            width / 2 + 50,
            height / 2 + 55,
            Graphics.FONT_TINY,
            stepsStr,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER
        );

        // --- TEP ---
        var hr = getHeartRate();
        if (hr != null && hr > 0) {
            var hrStr = Lang.format("$1$ bpm", [hr.format("%d")]);
            dc.setColor(Graphics.COLOR_RED, Graphics.COLOR_TRANSPARENT);
            dc.drawText(
                width / 2,
                height / 2 + 80,
                Graphics.FONT_TINY,
                hrStr,
                Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER
            );
        }

        // --- BLUETOOTH ---
        var connected = System.getDeviceSettings().phoneConnected;
        if (connected) {
            dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        } else {
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        }
        dc.fillCircle(width / 2, height - 25, 4);
    }

    //! Vrací barvu podle úrovně baterie.
    private function getBatteryColor(battery as Float) as Number {
        if (battery > 50.0) {
            return Graphics.COLOR_GREEN;
        } else if (battery > 20.0) {
            return Graphics.COLOR_YELLOW;
        } else {
            return Graphics.COLOR_RED;
        }
    }

    //! Nakreslí jednoduchou ikonu baterie.
    private function drawBatteryIcon(dc as Dc, x as Number, y as Number, battery as Float) as Void {
        dc.setColor(getBatteryColor(battery), Graphics.COLOR_TRANSPARENT);
        // Obrys baterie
        dc.drawRectangle(x, y, 16, 10);
        // Pól baterie
        dc.fillRectangle(x + 16, y + 3, 2, 4);
        // Výplň podle úrovně
        var fillWidth = ((battery / 100.0) * 14).toNumber();
        if (fillWidth < 1) {
            fillWidth = 1;
        }
        dc.fillRectangle(x + 1, y + 1, fillWidth, 8);
    }

    //! Získá aktuální tepovou frekvenci z Activity nebo ActivityMonitor.
    private function getHeartRate() as Number? {
        // Nejprve zkusíme aktuální aktivitu
        var actInfo = Activity.getActivityInfo();
        if (actInfo != null && actInfo.currentHeartRate != null) {
            return actInfo.currentHeartRate;
        }

        // Fallback: poslední známý tep z historie
        var hrIterator = ActivityMonitor.getHeartRateHistory(1, true);
        if (hrIterator != null) {
            var sample = hrIterator.next();
            if (sample != null && sample.heartRate != ActivityMonitor.INVALID_HR_SAMPLE) {
                return sample.heartRate;
            }
        }

        return null;
    }

    function onHide() as Void {
    }

    function onExitSleep() as Void {
    }

    function onEnterSleep() as Void {
    }
}
