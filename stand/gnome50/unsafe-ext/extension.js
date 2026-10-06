export default class UnsafeModeExtension {
    enable() {
        global.context.unsafe_mode = true;
    }

    disable() {
    }
}
