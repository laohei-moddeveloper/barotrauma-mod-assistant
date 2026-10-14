using System;
using System.IO;
using System.Windows;

namespace BaroEditor.Desktop
{
    internal static class Program
    {
        [STAThread]
        public static void Main(string[] args)
        {
            var app = new Application { ShutdownMode = ShutdownMode.OnMainWindowClose };
            app.DispatcherUnhandledException += (_, e) => { MessageBox.Show(e.Exception.Message, "BaroEditor", MessageBoxButton.OK, MessageBoxImage.Error); e.Handled = true; };
#if VALIDATION
            args = new[] { "--self-test" };
#endif
            try { app.Run(new MainWindow(args)); }
            catch (Exception e) { MessageBox.Show(e.Message, "BaroEditor 启动失败", MessageBoxButton.OK, MessageBoxImage.Error); }
        }
    }
}
