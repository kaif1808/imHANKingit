#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(arrow)
  library(basedosdados)
  library(bigrquery)
})

query <- "
WITH 
dicionario_id_verbete AS (
    SELECT
        chave AS chave_id_verbete,
        valor AS descricao_id_verbete
    FROM `basedosdados.br_bcb_estban.dicionario`
    WHERE
        TRUE
        AND nome_coluna = 'id_verbete'
        AND id_tabela = 'municipio'
)
SELECT
    dados.valor as valor,
    descricao_id_verbete AS id_verbete,
    dados.mes as mes,
    dados.id_municipio AS id_municipio,
    diretorio_id_municipio.nome AS id_municipio_nome,
    dados.sigla_uf AS sigla_uf,
    diretorio_sigla_uf.nome AS sigla_uf_nome,
    dados.agencias_esperadas as agencias_esperadas,
    dados.cnpj_basico as cnpj_basico,
    dados.instituicao as instituicao,
    dados.ano as ano,
    dados.agencias_processadas as agencias_processadas
FROM `basedosdados.br_bcb_estban.municipio` AS dados
LEFT JOIN `dicionario_id_verbete`
    ON dados.id_verbete = chave_id_verbete
LEFT JOIN (SELECT DISTINCT id_municipio,nome  FROM `basedosdados.br_bd_diretorios_brasil.municipio`) AS diretorio_id_municipio
    ON dados.id_municipio = diretorio_id_municipio.id_municipio
LEFT JOIN (SELECT DISTINCT sigla,nome  FROM `basedosdados.br_bd_diretorios_brasil.uf`) AS diretorio_sigla_uf
    ON dados.sigla_uf = diretorio_sigla_uf.sigla
"

default_output <- file.path("results", "tables", "br_bcb_estban_municipio.parquet")

parse_args <- function(args) {
  out <- list(
    billing_project_id = "databasos",
    output = default_output
  )

  if (!length(args)) {
    return(out)
  }

  for (arg in args) {
    if (grepl("^--billing-project-id=", arg)) {
      out$billing_project_id <- sub("^--billing-project-id=", "", arg)
    } else if (grepl("^--output=", arg)) {
      out$output <- sub("^--output=", "", arg)
    } else {
      stop(
        "Unknown argument: ", arg,
        "\nSupported args: --billing-project-id=..., --output=..."
      )
    }
  }

  out
}

args <- parse_args(commandArgs(trailingOnly = TRUE))
output_parquet <- normalizePath(dirname(args$output), mustWork = FALSE)
output_parquet <- file.path(output_parquet, basename(args$output))
output_dir <- dirname(output_parquet)

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

if (file.exists(output_parquet)) {
  file.remove(output_parquet)
}

message("Setting billing project: ", args$billing_project_id)
set_billing_id(args$billing_project_id)

message("Submitting query job")
query_table <- bq_project_query(args$billing_project_id, query)

download_chunk_rows <- 100000L
downloaded_rows <- 0L
total_rows <- bq_table_nrow(query_table)
message("Query result rows: ", format(total_rows, big.mark = ","))
message("Downloading in chunks of ", format(download_chunk_rows, big.mark = ","), " rows")

sink <- FileOutputStream$create(output_parquet)
writer <- NULL
on.exit({
  if (!is.null(writer)) {
    try(writer$Close(), silent = TRUE)
  }
  try(sink$close(), silent = TRUE)
}, add = TRUE)

repeat {
  chunk <- bq_table_download(
    query_table,
    n_max = download_chunk_rows,
    start_index = downloaded_rows,
    api = "json",
    billing = args$billing_project_id,
    bigint = "integer64",
    quiet = TRUE
  )

  chunk_rows <- nrow(chunk)
  if (chunk_rows == 0L) {
    break
  }

  chunk_table <- as_arrow_table(chunk)
  if (is.null(writer)) {
    writer <- ParquetFileWriter$create(
      chunk_table$schema,
      sink,
      properties = ParquetWriterProperties$create(
        column_names = names(chunk),
        compression = "snappy",
        write_statistics = TRUE
      )
    )
  }

  writer$WriteTable(chunk_table, chunk_size = chunk_rows)

  downloaded_rows <- downloaded_rows + chunk_rows
  message(
    "  downloaded ", format(downloaded_rows, big.mark = ","),
    " / ", format(total_rows, big.mark = ","),
    " rows"
  )

  rm(chunk, chunk_table)
  gc()

  if (downloaded_rows >= total_rows || chunk_rows < download_chunk_rows) {
    break
  }
}

if (is.null(writer)) {
  stop("Query returned no rows; no parquet file was written.")
}

writer$Close()
sink$close()
message("Wrote Parquet file: ", output_parquet)
