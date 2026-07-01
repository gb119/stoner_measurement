# Incremental Save Mode - Simplified Developer Specification

## **1. Applicability**

The *save* command plugin supports two modes:

- **Trace mode**
- **Data mode** - where a looping sequence command produces a dataframe that may be periodically saved.

Incremental save applies **only** to *data mode*. It allows the plugin to write new rows to disk during
long-running loops, reducing data loss if the program crashes.

---

## **2. User Interface**

In the save plugin configuration panel:

- The user chooses **Save as Trace** or **Save Data**.
- In both modes there is a boolean switch to **avoid overwriting files**
- If **Save Data** is selected, the user may enable **Save Incrementally** (boolean switch).

---

## **3. Internal State**

The plugin must maintain an internal dictionary for the current program run:

```yaml
{
    original_filename: {
        actual_filename: <string>,
        rows_saved: <int>
    },
    ...
}
```

This dictionary is initialised during the plugin’s connect/configure phase.

---

## **4. Incremental Save Operation**

When the save command is executed in **incremental mode**, the plugin must perform the following steps:

### **Step 1 - Determine filenames**

- Compute the **original filename**.
- Apply the **non-overwrite flag** to obtain the **actual filename** used on disk.

### **Step 2 - Load or initialise tracking info**

- If the original filename is **not** in the internal dictionary:
  - Store the actual filename.
  - Set `rows_saved = 0`.
- If it **is** present:
  - Retrieve the stored actual filename and `rows_saved`.

### **Step 3 - Compare saved vs available rows**

Let:

- `saved = rows_saved`
- `meta_rows = number of metadata rows`
- `data_rows = number of data rows currently available`

### **Step 4 - Decide write behaviour**

- **Case A: `saved < meta_rows`**  
  Write the **entire file** (metadata + all current data rows) to the actual filename.

- **Case B: `saved >= meta_rows`**  
  Append only the **new data rows**, i.e. rows from index `saved` up to `data_rows - 1`, provided there is
  at least one new row.

### **Step 5 - Update internal state**

Set `rows_saved = data_rows` for this file.

---

## **5. Non-Incremental Save Operation**

If incremental mode is **not** enabled:

1. Compute original and actual filenames (respecting non-overwrite rules).
2. Write the **entire file** (metadata + all data rows).
3. Record in the internal dictionary:
   - original filename
   - actual filename
   - total number of data rows written

---
