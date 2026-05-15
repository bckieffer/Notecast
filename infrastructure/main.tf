terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }

  # Recommended: move state to S3 once the bucket exists.
  # backend "s3" {
  #   bucket         = "your-terraform-state-bucket"
  #   key            = "notecast/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

provider "aws" {
  region = var.aws_region
}

provider "github" {
  token = var.github_token
  owner = var.github_owner
}
