class DummyPlugin:
    def __init__(self):
        self.scan_generator = SteppedScanGenerator()  # default to SteppedScanGenerator
        # Ensure no stages by calling the appropriate method if necessary.
        self.scan_generator.stages = []  # no stages to yield only the start point

    def set_scan_generator_class(self, new_generator_class):
        if new_generator_class is not self.scan_generator.__class__:
            self.scan_generator.__class__ = new_generator_class  # change the generator class
            self.emit('scan_generator_changed')  # emit event if changed
        # If unchanged, do nothing (noop).