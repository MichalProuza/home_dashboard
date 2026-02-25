import Toybox.Application;
import Toybox.WatchUi;

//! Hlavní třída aplikace ciferníku Home Dashboard.
class HomeDashboardApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state as Dictionary?) as Void {
    }

    function onStop(state as Dictionary?) as Void {
    }

    //! Vrací počáteční view ciferníku.
    function getInitialView() as [Views] or [Views, InputDelegates] {
        return [new HomeDashboardView()];
    }
}
