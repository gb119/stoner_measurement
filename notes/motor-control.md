# Motor Control Logic - Simplified Developer Specification

## **1. Hardware Model**

Each motor instrument in `stoner_measurement.instruments` represents a **single-axis continuous-rotation
motor** with:

- direction (CW / CCW / shortest)
- velocity
- acceleration
- target angle

Physically, the motor drives a shaft that **must not rotate beyond +/- soft-limit** unless the user explicitly
approves an override.

### Controller connections

Most motor drivers use one of the shared Serial, GPIB, Ethernet, or Null
transports. Thorlabs Kinesis drivers are different: pylablib speaks the
APT/Kinesis protocol directly through the controller's FTDI USB interface, so
they do not use a generic byte transport or load the Kinesis .NET assemblies.

For `ThorlabsHDR50` and `ThorlabsKDC101KPRMTE`, select **Kinesis USB** in the
motor panel and enter the controller serial number printed on the device. The
engine passes that serial number to pylablib's Kinesis driver, which discovers
and opens the USB controller. This requires the `pyft232` Python package and
the FTDI D2XX/CDM driver (`ftd2xx.dll`) on Windows, but does not require CLR
assembly-path or `PATH` configuration for `Thorlabs.MotionControl.*.dll`. The
selected driver, `Kinesis USB` transport label, and serial number are persisted
in `motor_controller.yaml` in the standard `connection` fields.

On Windows the driver adds the default
`C:\Program Files\Thorlabs\Kinesis` installation directory to Python's DLL
search path before importing `pyft232`. For a non-default installation, set
`THORLABS_KINESIS_DIR` to the directory containing the 64-bit `ftd2xx.dll`.

---

## **2. Soft Limit Definition**

- The there is a **soft limit** (typically 180-260 degrees).
- This value is stored in the motor-controller YAML configuration but is not editable by the user in the UI.
- The motor must **not** rotate:
  - clockwise past `+soft_limit`
  - counter-clockwise past `-soft_limit`
- The motor controller engine enforces this unless the caller explicitly sets `force=True`.

---

## **3. Direction Modes**

Direction is a three-state setting:

1. **clockwise (CW)** - angle increases  
2. **counter-clockwise (CCW)** - angle decreases  
3. **shortest** - controller chooses CW or CCW based on which requires the smaller rotation

---

## **4. Motion Calculation Algorithm**

Let:

- `current` = current motor angle  
- `target` = requested target angle  
- `soft_limit` = positive soft limit (range is `[-soft_limit, +soft_limit]`)  

### **Step 1 - Normalise angles into soft-limit range**

If `current` or `target` lies outside `[-soft_limit, +soft_limit]`, adjust by adding or subtracting multiples
of 360 degrees until both angles lie within the allowed range.

### **Step 2 - Apply fixed direction rules**

- **If direction = CW**  
  If `target < current`, add 360 degrees repeatedly until `target > current`.

- **If direction = CCW**  
  If `target > current`, subtract 360 degrees repeatedly until `target < current`.

### **Step 3 — Soft-limit enforcement**

After adjustments:

- If `target` is outside `[-soft_limit, +soft_limit]`:
  - Raise `ValueError` unless `force=True`.
  - Only the **panel** should ever call with `force=True`, and only after explicit user confirmation.

### **Step 4 - Shortest-direction logic**

If direction = **shortest**:

- If `target < current`, choose **CCW**.
- If `target > current`, choose **CW**.

### **Step 5 - Compute relative motion**

The motor should be instructed using **relative rotation**, not absolute angles:

```text
relative_angle = abs(target - current)
direction = CW or CCW (as determined above)
```

This ensures correct behaviour for wrap-around cases.  
Example:  
`current = -190`, `target = +190`, `soft_limit = 200` ->  
Correct motion is **+380 degrees CW**, not a wrapped 0-360 degree shortcut.

---

## **5. Soft-Limit Override (Dangerous Motion)**

Occasionally the user may need to perform a rotation that exceeds the soft limit.

Rules:

1. The engine **must** raise `ValueError` whenever a motion violates the soft limit and `force=False`.
2. The **panel** catches this error and:
   - prompts the user for confirmation,
   - retries the motion with `force=True` if the user approves.
3. The user should be advised to **reset the home position** after any forced motion.
4. Plugin-generated code must **never** set `force=True`.
