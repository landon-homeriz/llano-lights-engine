/* Llano Lights.app's own program (Contents/MacOS/Llano Lights), Llano BL #12517.
 *
 * It only finds the bundle it sits in and runs the bundled Python on the app:
 *   Contents/Resources/Llano-Lights/runtime/bin/python3 -E -s .../app/gigbar_app.py [what it was given]
 * with the app folder as the working folder. -E and -s keep any Python setup on the Mac (PYTHONPATH,
 * a user site folder) out of it. exec, not a child: the Python IS the app's process, so the Mac's
 * permissions (Apple Events, audio) are asked for and kept as Llano Lights'.
 * Built for Apple Silicon and Intel by mac/build.py (zig cc) and joined into one universal file.
 */
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int up(char *path, int levels) {
    while (levels-- > 0) {
        char *slash = strrchr(path, '/');
        if (!slash || slash == path) return 0;
        *slash = '\0';
    }
    return 1;
}

int main(int argc, char **argv) {
    char exe[PATH_MAX], real[PATH_MAX], python[PATH_MAX], app[PATH_MAX], script[PATH_MAX];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real) || !up(real, 2)) {
        fprintf(stderr, "Llano Lights: can't find its own folder\n");
        return 70;
    }
    /* real is now .../Llano Lights.app/Contents */
    snprintf(python, sizeof python, "%s/Resources/Llano-Lights/runtime/bin/python3", real);
    snprintf(app, sizeof app, "%s/Resources/Llano-Lights/app", real);
    snprintf(script, sizeof script, "%s/gigbar_app.py", app);
    if (chdir(app) != 0) {
        fprintf(stderr, "Llano Lights: can't open %s\n", app);
        return 70;
    }
    /* Python's compiled caches go to ~/Library/Caches, never inside the app: a file written into a
       signed bundle breaks its seal (codesign --verify fails on the installed app). */
    char cache[PATH_MAX + 32];
    const char *home = getenv("HOME");
    snprintf(cache, sizeof cache, "pycache_prefix=%s/Library/Caches/Llano Lights/pycache", home ? home : "/tmp");
    char **args = calloc((size_t)argc + 7, sizeof *args);
    if (!args) return 71;
    int n = 0;
    args[n++] = python;
    args[n++] = "-E";
    args[n++] = "-s";
    args[n++] = "-X";
    args[n++] = cache;
    args[n++] = script;
    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "-psn_", 5) == 0) continue;   /* an old macOS adds a process serial number */
        args[n++] = argv[i];
    }
    args[n] = NULL;
    execv(python, args);
    perror("Llano Lights: can't start its Python");
    return 71;
}
