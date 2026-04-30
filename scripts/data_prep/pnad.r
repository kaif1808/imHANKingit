library(data.table)

# Columns required by the PNADC pipeline in `htm_classification.py`
vars_needed <- c(
  # Core identifiers and time/state
  "Ano", "Trimestre", "UF",
  # Age and demographics (test-format and raw)
  "faixa_idade", "V2009",
  "sexo", "V2007",
  # Education (test-format and raw)
  "faixa_educ", "VD3004",
  # Weights and income
  "Habitual", "V1028",
  "rendimento_habitual_real",
  # Household structure (test-format and raw)
  "ID_DOMICILIO", "V2001",
  # Labour status flags (if present)
  "formal", "informal", "ocupado", "desocupado",
  "conta_propria", "fora_forca_trab",
  # ID Numbers
  "id_dom", "id_ind", "id_rs", "num_appearances"
)

process_panel <- function(panel_id) {
  input_path <- file.path("PNAD-C-Treated", sprintf("pnadc_panel_%d.csv", panel_id))
  if (!file.exists(input_path)) {
    message("File not found, skipping: ", input_path)
    return(invisible(NULL))
  }

  message("Reading: ", input_path)
  dt <- fread(input_path)
  dt <- dt[, intersect(vars_needed, names(dt)), with = FALSE]

  output_path <- file.path("PNAD-C-Treated", sprintf("test%d.csv", panel_id))
  message(
    "Writing: ", output_path,
    " (rows: ", nrow(dt), ", cols: ", ncol(dt), ")"
  )
  fwrite(dt, output_path)

  rm(dt)
  gc()

  invisible(NULL)
}

panels <- c(5L, 6L, 7L)
invisible(lapply(panels, process_panel))
